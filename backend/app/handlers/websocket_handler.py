"""WebSocket handler for relaying messages between client and OpenAI."""
import asyncio
import json
import time
import logging
import traceback
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from app.presentation import presentation_manager
from app.tools.tool_handler import ToolHandler
from app.services.session_service import SessionService
from app.services.conversation_service import ConversationService
from app.config.tools import TOOL_DEFINITIONS
from app.utils.errors import send_error_safe

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """Handles WebSocket connections and message relaying."""
    
    def __init__(self):
        """Initialize WebSocket handler with required services."""
        self.tool_handler = ToolHandler(presentation_manager)
        self.session_service = SessionService(presentation_manager)
        self.conversation_service = ConversationService(presentation_manager)
    
    async def relay_messages(self, client_ws: WebSocket, vendor_ws) -> None:
        """Relay messages between client and OpenAI WebSockets with format conversion.
        
        Args:
            client_ws: WebSocket connection to client
            vendor_ws: WebSocket connection to OpenAI
        """
        session_configured = False
        
        async def client_to_vendor():
            """Relay messages from client to OpenAI, converting format."""
            try:
                while True:
                    data = await client_ws.receive_json()
                    
                    if data.get("type") == "audio":
                        audio_b64 = data.get("data")
                        if audio_b64:
                            openai_message = {
                                "type": "input_audio_buffer.append",
                                "audio": audio_b64
                            }
                            await vendor_ws.send(json.dumps(openai_message))
                    
                    elif data.get("type") == "audio_commit":
                        commit_message = {"type": "input_audio_buffer.commit"}
                        await vendor_ws.send(json.dumps(commit_message))
                    
                    elif data.get("type") == "interrupt":
                        cancel_message = {"type": "response.cancel"}
                        await vendor_ws.send(json.dumps(cancel_message))
                    
                    elif data.get("type") == "start_presentation":
                        await self._handle_start_presentation(client_ws, vendor_ws)
                    
                    elif data.get("type") == "navigate_slide":
                        await self._handle_navigate_slide(data, client_ws)
                    
                    elif data.get("type") == "session.update":
                        await vendor_ws.send(json.dumps(data))
                    
                    else:
                        await vendor_ws.send(json.dumps(data))
                        
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.error(f"Error in client_to_vendor: {e}")
                traceback.print_exc()
                try:
                    await client_ws.send_json({
                        "type": "error",
                        "error": f"Error processing client message: {str(e)}",
                        "error_type": "client_to_vendor_error"
                    })
                except:
                    pass
        
        async def vendor_to_client():
            """Relay messages from OpenAI to client, converting format."""
            nonlocal session_configured
            response_state = {
                "current_response_id": None,
                "current_response_has_function_call": False,
                "handled_call_ids": set()
            }
            
            try:
                while True:
                    message = await vendor_ws.recv()
                    
                    if isinstance(message, bytes):
                        logger.warning("Received binary message from OpenAI, skipping")
                        continue
                    
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON from OpenAI. Error: {e}")
                        try:
                            await client_ws.send_json({
                                "type": "error",
                                "error": f"Invalid JSON from OpenAI: {str(e)}",
                                "error_type": "openai_json_error"
                            })
                        except:
                            pass
                        continue
                    
                    event_type = data.get("type")
                    
                    # Handle server.hello
                    if event_type == "server.hello" and not session_configured:
                        session_configured = True
                        await self._handle_server_hello(data, client_ws, vendor_ws)
                        continue
                    
                    # Handle various event types
                    await self._handle_openai_event(
                        event_type, data, client_ws, vendor_ws, response_state
                    )
                    
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"OpenAI WebSocket disconnected: {e}")
                try:
                    await client_ws.send_json({
                        "type": "error",
                        "error": "OpenAI connection closed",
                        "error_type": "openai_disconnected"
                    })
                except:
                    pass
            except Exception as e:
                logger.error(f"Error in vendor_to_client: {e}")
                traceback.print_exc()
                try:
                    await client_ws.send_json({
                        "type": "error",
                        "error": f"Error processing OpenAI message: {str(e)}",
                        "error_type": "vendor_to_client_error"
                    })
                except:
                    pass
        
        # Run both relay tasks concurrently
        tasks = [
            asyncio.create_task(client_to_vendor()),
            asyncio.create_task(vendor_to_client()),
        ]
        
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error cancelling task: {e}")
    
    async def _handle_start_presentation(self, client_ws: WebSocket, vendor_ws) -> None:
        """Handle start_presentation message from client."""
        if not presentation_manager.slides:
            logger.error("No presentation loaded! Cannot start presentation.")
            await client_ws.send_json({
                "type": "error",
                "error": "No presentation loaded. Please upload a presentation first.",
                "error_type": "no_presentation"
            })
            return
        
        # Update session config
        await self.session_service.send_session_config(vendor_ws)
        await asyncio.sleep(1.5)
        
        # Add presentation data as conversation items
        await self.conversation_service.add_presentation_to_conversation(vendor_ws)
        await asyncio.sleep(0.5)
        
        # Navigate to first slide
        result = presentation_manager.navigate_to_slide("jump", 0)
        slide_data = result.get("slide", {})
        if "index" not in slide_data:
            slide_data["index"] = 0
        
        await client_ws.send_json({
            "type": "slide_changed",
            "slide_index": 0,
            "total_slides": result.get("total_slides", 0),
            "slide": slide_data,
        })
        
        # Send start message
        start_message_text = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "Start presenting the presentation. Begin with slide 1."
                }]
            }
        }
        await vendor_ws.send(json.dumps(start_message_text))
        await asyncio.sleep(0.3)
        
        # Request response
        total_slides = len(presentation_manager.slides)
        start_message = {
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"],
                "tool_choice": "auto" if total_slides <= 5 else "required"
            }
        }
        await vendor_ws.send(json.dumps(start_message))
    
    async def _handle_navigate_slide(self, data: dict, client_ws: WebSocket) -> None:
        """Handle manual slide navigation from client."""
        action = data.get("action")
        slide_index = data.get("slide_index")
        result = presentation_manager.navigate_to_slide(action, slide_index)
        
        await client_ws.send_json({
            "type": "slide_changed",
            "slide_index": result.get("current_slide", 0),
            "total_slides": result.get("total_slides", 0),
            "slide": result.get("slide", {}),
        })
    
    async def _handle_server_hello(
        self, 
        data: dict, 
        client_ws: WebSocket, 
        vendor_ws
    ) -> None:
        """Handle server.hello event from OpenAI."""
        if presentation_manager.slides:
            await self.session_service.send_session_config(vendor_ws)
        else:
            # Send minimal config
            minimal_config = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio"],
                    "voice": "alloy",
                    "instructions": "You are a PowerPoint presentation assistant. Wait for the user to upload a presentation.",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 200,
                        "interrupt_response": True,
                    },
                    "tools": TOOL_DEFINITIONS,
                    "tool_choice": "auto",
                }
            }
            await vendor_ws.send(json.dumps(minimal_config))
        
        await client_ws.send_json({
            "type": "server.hello",
            "session": data.get("session", {})
        })
    
    async def _handle_openai_event(
        self,
        event_type: str,
        data: dict,
        client_ws: WebSocket,
        vendor_ws,
        response_state: dict
    ) -> None:
        """Handle various OpenAI event types."""
        # Audio events
        if event_type == "response.audio.delta":
            delta = data.get("delta", "")
            if delta:
                await client_ws.send_json({"type": "audio", "data": delta})
        
        # Output item events
        elif event_type == "response.output_item.added":
            await self._handle_output_item_added(data, client_ws, vendor_ws, response_state)
        
        # Text events
        elif event_type == "response.text.delta":
            text_delta = data.get("delta", "")
            await client_ws.send_json({
                "type": "text",
                "text": text_delta,
                "role": "assistant"
            })
        
        # Function call events
        elif event_type == "response.function_call_arguments.done":
            await self._handle_function_call_done(data, vendor_ws, client_ws, response_state)
        
        # Conversation events
        elif event_type == "conversation.item.input_audio_transcription.completed":
            await self._handle_transcription(data, client_ws)
        
        elif event_type == "conversation.item.created":
            await self._handle_conversation_item_created(data, vendor_ws, client_ws, response_state)
        
        # Response events
        elif event_type == "response.text.done":
            await self._handle_text_done(data, vendor_ws, client_ws)
        
        elif event_type == "response.output_item.done":
            await self._handle_output_item_done(data, vendor_ws, client_ws, response_state)
        
        elif event_type == "response.created":
            response_obj = data.get("response", {})
            if isinstance(response_obj, dict):
                response_id = response_obj.get("id")
                if response_id:
                    response_state["current_response_id"] = response_id
                    response_state["current_response_has_function_call"] = False
            await client_ws.send_json({"type": "response.created"})
        
        elif event_type == "response.started":
            response_id = data.get("response", {}).get("id") if isinstance(data.get("response"), dict) else None
            if response_id:
                response_state["current_response_id"] = response_id
                response_state["current_response_has_function_call"] = False
            await client_ws.send_json({"type": "response.started"})
        
        elif event_type == "response.done":
            await self._handle_response_done(data, client_ws, response_state)
        
        elif event_type == "response.interrupted":
            await client_ws.send_json({"type": "interrupted"})
        
        # Audio buffer events - map to frontend-expected format
        elif event_type == "input_audio_buffer.speech_started":
            # Frontend expects "speech_started" to clear audio queue on interruption
            await client_ws.send_json({"type": "speech_started"})
        
        elif event_type == "input_audio_buffer.speech_stopped":
            await client_ws.send_json({"type": "speech_stopped"})
        
        elif event_type == "input_audio_buffer.committed":
            await client_ws.send_json({"type": "input_audio_buffer.committed"})
        
        elif event_type == "output_audio_buffer.started":
            await client_ws.send_json({"type": "output_audio_buffer.started"})
        
        elif event_type == "output_audio_buffer.speech_started":
            await client_ws.send_json({"type": "output_audio_buffer.speech_started"})
        
        elif event_type == "output_audio_buffer.speech_stopped":
            await client_ws.send_json({"type": "output_audio_buffer.speech_stopped"})
        
        elif event_type == "output_audio_buffer.interrupted":
            # Frontend expects this to clear audio queue
            await client_ws.send_json({"type": "output_audio_buffer.interrupted"})
        
        elif event_type == "session.created":
            await client_ws.send_json({"type": "session.created"})
        
        # Error events
        elif event_type == "error":
            await client_ws.send_json({
                "type": "error",
                "error": str(data)
            })
            logger.error(f"OpenAI Error: {data}")
        
        # Unknown events
        else:
            await client_ws.send_json(data)
    
    async def _handle_output_item_added(
        self, 
        data: dict, 
        client_ws: WebSocket, 
        vendor_ws,
        response_state: dict
    ) -> None:
        """Handle response.output_item.added event."""
        item = data.get("item", {})
        item_type = item.get("type")
        
        if item_type == "function_call":
            response_state["current_response_has_function_call"] = True
        
        elif item_type == "audio":
            audio_data = item.get("audio", "") or item.get("data", "")
            if not audio_data and isinstance(item.get("audio"), dict):
                audio_data = item.get("audio", {}).get("data", "")
            if audio_data:
                await client_ws.send_json({"type": "audio", "data": audio_data})
        
        elif item_type == "text":
            text = item.get("text", "")
            if text:
                if await self._check_json_tool_call(text, vendor_ws, client_ws):
                    return
                await client_ws.send_json({
                    "type": "text",
                    "text": text,
                    "role": "assistant"
                })
    
    async def _handle_function_call_done(
        self,
        data: dict,
        vendor_ws,
        client_ws: WebSocket,
        response_state: dict
    ) -> None:
        """Handle response.function_call_arguments.done event."""
        function_name = data.get("name", "")
        call_id = data.get("call_id", "")
        arguments_str = data.get("arguments", "{}")
        
        handled_call_ids = response_state["handled_call_ids"]
        if function_name and call_id and call_id not in handled_call_ids:
            handled_call_ids.add(call_id)
            await self.tool_handler.handle_tool_call(vendor_ws, client_ws, {
                "name": function_name,
                "call_id": call_id,
                "arguments": arguments_str
            })
        elif not function_name or not call_id:
            logger.warning("response.function_call_arguments.done missing function_name or call_id")
    
    async def _handle_transcription(self, data: dict, client_ws: WebSocket) -> None:
        """Handle transcription events."""
        item = data.get("item", {})
        transcript = item.get("transcript", "")
        if transcript:
            await client_ws.send_json({
                "type": "text",
                "text": transcript,
                "role": "user"
            })
    
    async def _handle_conversation_item_created(
        self,
        data: dict,
        vendor_ws,
        client_ws: WebSocket,
        response_state: dict
    ) -> None:
        """Handle conversation.item.created event."""
        item = data.get("item", {})
        item_type = item.get("type")
        
        if item_type == "input_audio_transcription":
            transcript = item.get("transcript", "")
            if transcript:
                await client_ws.send_json({
                    "type": "text",
                    "text": transcript,
                    "role": "user"
                })
        
        elif item_type == "function_call":
            call_id = item.get('call_id', '')
            arguments_str = item.get('arguments', '')
            handled_call_ids = response_state["handled_call_ids"]
            
            if not arguments_str or arguments_str == "":
                response_state["current_response_has_function_call"] = True
            elif call_id and call_id not in handled_call_ids:
                handled_call_ids.add(call_id)
                response_state["current_response_has_function_call"] = True
                await self.tool_handler.handle_tool_call(vendor_ws, client_ws, item)
    
    async def _handle_text_done(self, data: dict, vendor_ws, client_ws: WebSocket) -> None:
        """Handle response.text.done event."""
        text = data.get("text", "")
        if text:
            await self._check_json_tool_call(text, vendor_ws, client_ws)
    
    async def _handle_output_item_done(
        self,
        data: dict,
        vendor_ws,
        client_ws: WebSocket,
        response_state: dict
    ) -> None:
        """Handle response.output_item.done event."""
        item = data.get("item", {})
        item_type = item.get("type")
        
        if item_type == "function_call":
            call_id = item.get('call_id', '')
            handled_call_ids = response_state["handled_call_ids"]
            if call_id and call_id not in handled_call_ids:
                handled_call_ids.add(call_id)
                response_state["current_response_has_function_call"] = True
                await self.tool_handler.handle_tool_call(vendor_ws, client_ws, item)
        
        elif item_type == "audio":
            audio_data = item.get("audio", "")
            if audio_data:
                await client_ws.send_json({"type": "audio", "data": audio_data})
        
        elif item_type == "text":
            text = item.get("text", "")
            if text:
                if await self._check_json_tool_call(text, vendor_ws, client_ws):
                    return
                await client_ws.send_json({
                    "type": "text",
                    "text": text,
                    "role": "assistant"
                })
    
    async def _handle_response_done(self, data: dict, client_ws: WebSocket, response_state: dict) -> None:
        """Handle response.done event."""
        await client_ws.send_json({"type": "response.done"})
        response_obj = data.get("response", {})
        if isinstance(response_obj, dict):
            output_items = response_obj.get("output", [])
            if output_items:
                for item in output_items:
                    if item.get("type") == "audio":
                        audio_data = item.get("audio", "")
                        if audio_data:
                            await client_ws.send_json({
                                "type": "audio",
                                "data": audio_data
                            })
        # Reset tracking for next response
        response_state["current_response_id"] = None
        response_state["current_response_has_function_call"] = False
    
    async def _check_json_tool_call(
        self, 
        text: str, 
        vendor_ws, 
        client_ws: WebSocket
    ) -> bool:
        """Check if text is JSON that should be converted to a tool call.
        
        Returns:
            True if JSON was converted to tool call, False otherwise
        """
        try:
            parsed_json = json.loads(text.strip())
            if isinstance(parsed_json, dict) and "slide_number" in parsed_json:
                slide_num = parsed_json["slide_number"]
                logger.warning(f"AI output JSON instead of calling tool! Converting to show_slide({slide_num})")
                await self.tool_handler.handle_tool_call(vendor_ws, client_ws, {
                    "name": "show_slide",
                    "call_id": f"auto_{slide_num}_{int(time.time())}",
                    "arguments": json.dumps({"slide_number": slide_num})
                })
                return True
        except (json.JSONDecodeError, ValueError):
            pass
        return False

