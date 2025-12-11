import asyncio
import os
import json
import logging
import websockets
import traceback
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_REALTIME_URL = os.getenv(
    "OPENAI_REALTIME_URL",
    "wss://api.openai.com/v1/realtime?model=gpt-realtime"
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Headers for OpenAI connection (as dict, matching reference implementation)
def get_openai_headers():
    """Get headers for OpenAI WebSocket connection."""
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "openai-beta": "realtime=v1",  # Lowercase to match OpenAI spec
    }


async def send_error_safe(ws: WebSocket, error_type: str, error_message: str):
    """Safely send error messages to the client WebSocket as JSON."""
    try:
        await ws.send_json({
            "type": "error",
            "error": error_message,
            "error_type": error_type
        })
    except Exception as e:
        logger.error(f"Error sending error message to client: {e}")


async def send_session_config(vendor_ws):
    """Send initial session configuration to OpenAI."""
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["audio"],
            "voice": "alloy",
            "instructions": "You are a helpful assistant. Speak naturally.",
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": "whisper-1"
            },
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 200,
                "interrupt_response": True,  # Allow user to interrupt assistant's responses
            },
        }
    }
    
    await vendor_ws.send(json.dumps(session_config))
    logger.info("Session configuration sent to OpenAI")


async def relay_messages(client_ws: WebSocket, vendor_ws):
    """Relay messages between client and OpenAI WebSockets with format conversion."""
    
    # Track if we've received server.hello and sent session config
    session_configured = False
    
    async def client_to_vendor():
        """Relay messages from client to OpenAI, converting format."""
        try:
            while True:
                # Receive JSON from client
                data = await client_ws.receive_json()
                
                if data.get("type") == "audio":
                    # Convert our format to OpenAI format
                    audio_b64 = data.get("data")
                    if audio_b64:
                        openai_message = {
                            "type": "input_audio_buffer.append",
                            "audio": audio_b64
                        }
                        await vendor_ws.send(json.dumps(openai_message))
                        logger.debug(f"Sent audio chunk to OpenAI ({len(audio_b64)} chars)")
                
                elif data.get("type") == "audio_commit":
                    # Client signals end of audio input
                    commit_message = {
                        "type": "input_audio_buffer.commit"
                    }
                    await vendor_ws.send(json.dumps(commit_message))
                    logger.debug("Committed audio buffer to OpenAI")
                
                elif data.get("type") == "interrupt":
                    # Cancel current response
                    cancel_message = {
                        "type": "response.cancel"
                    }
                    await vendor_ws.send(json.dumps(cancel_message))
                    logger.info("Cancelled OpenAI response")
                
                elif data.get("type") == "session.update":
                    # Forward session update directly
                    await vendor_ws.send(json.dumps(data))
                    logger.info("Forwarded session update to OpenAI")
                
                else:
                    # Forward other messages as-is
                    await vendor_ws.send(json.dumps(data))
                    logger.debug(f"Forwarded message to OpenAI: {data.get('type')}")
                    
        except WebSocketDisconnect:
            logger.info("Client WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error in client_to_vendor: {e}")
            traceback.print_exc()
            # Try to send error to client if still connected
            try:
                await client_ws.send_json({
                    "type": "error",
                    "error": f"Error processing client message: {str(e)}",
                    "error_type": "client_to_vendor_error"
                })
            except:
                pass  # Client may already be disconnected
    
    async def vendor_to_client():
        """Relay messages from OpenAI to client, converting format."""
        nonlocal session_configured
        try:
            while True:
                # Receive message from OpenAI (could be text or binary)
                message = await vendor_ws.recv()
                
                # Handle binary messages (shouldn't happen with OpenAI Realtime API, but be safe)
                if isinstance(message, bytes):
                    logger.warning("Received binary message from OpenAI, skipping")
                    continue
                
                # Parse JSON string
                try:
                    data = json.loads(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from OpenAI. Error: {e}")
                    logger.error(f"Message preview (first 500 chars): {message[:500]}")
                    # Send error to client
                    try:
                        await client_ws.send_json({
                            "type": "error",
                            "error": f"Invalid JSON from OpenAI: {str(e)}",
                            "error_type": "openai_json_error"
                        })
                    except:
                        pass
                    continue
                
                # Log the event type for debugging
                event_type = data.get("type")
                if event_type:
                    # Always log ALL events at INFO level for debugging
                    logger.info(f"📨 Received OpenAI event: {event_type}")
                    
                    # Log response-related events with more detail
                    if event_type.startswith("response."):
                        logger.info(f"   📢 Response event: {event_type}")
                        # Log response details for debugging
                        if "response" in data:
                            resp_data = data.get("response", {})
                            if isinstance(resp_data, dict):
                                logger.info(f"   Response keys: {list(resp_data.keys())}")
                                # Log status if available
                                if "status" in resp_data:
                                    logger.info(f"   Response status: {resp_data.get('status')}")
                                # Log output if available
                                if "output" in resp_data:
                                    output = resp_data.get("output", [])
                                    logger.info(f"   Response output items: {len(output)}")
                                    for idx, item in enumerate(output):
                                        logger.info(f"     Item {idx}: {item.get('type', 'unknown')}")
                    
                    # Log full event for audio-related events
                    if "audio" in event_type.lower():
                        logger.info(f"   🎵 Audio event - keys: {list(data.keys())}")
                        if "delta" in data:
                            delta_size = len(data.get("delta", ""))
                            logger.info(f"   Audio delta size: {delta_size} chars")
                        elif "audio" in data:
                            audio_size = len(str(data.get("audio", "")))
                            logger.info(f"   Audio data size: {audio_size} chars")
                        else:
                            logger.info(f"   No audio data found, all keys: {list(data.keys())}")
                    
                    # Log full data for response events to debug
                    if event_type.startswith("response."):
                        event_preview = json.dumps(data)[:800]
                        logger.info(f"   Full event data: {event_preview}")
                
                # Handle server.hello - send session config after receiving it
                if event_type == "server.hello" and not session_configured:
                    logger.info("Received server.hello, sending session config")
                    session_configured = True
                    await send_session_config(vendor_ws)
                    # Forward server.hello to client
                    await client_ws.send_json({
                        "type": "server.hello",
                        "session": data.get("session", {})
                    })
                    continue
                
                # Convert OpenAI format to our client format
                if event_type == "response.audio.delta":
                    # Audio chunk from OpenAI
                    delta = data.get("delta", "")
                    if delta:
                        logger.info(f"🎵 Sending audio delta to client ({len(delta)} chars)")
                        await client_ws.send_json({
                            "type": "audio",
                            "data": delta
                        })
                    else:
                        logger.warning("Received response.audio.delta with empty delta")
                
                elif event_type == "response.output_item.added":
                    # Output item added (could be audio or text)
                    item = data.get("item", {})
                    item_type = item.get("type")
                    logger.info(f"🎯 Output item added: {item_type}")
                    logger.info(f"   Item keys: {list(item.keys())}")
                    
                    if item_type == "audio":
                        # Audio item added - check all possible audio fields
                        audio_data = item.get("audio", "")
                        if not audio_data:
                            # Try other possible fields
                            audio_data = item.get("data", "")
                        if not audio_data:
                            # Check if it's in a nested structure
                            audio_obj = item.get("audio", {})
                            if isinstance(audio_obj, dict):
                                audio_data = audio_obj.get("data", "")
                        
                        if audio_data:
                            logger.info(f"🎵 Sending audio item to client ({len(audio_data)} chars)")
                            await client_ws.send_json({
                                "type": "audio",
                                "data": audio_data
                            })
                        else:
                            logger.warning(f"⚠️ Audio item has no audio data. Item structure: {json.dumps(item)[:200]}")
                    elif item_type == "text":
                        # Text item added
                        text = item.get("text", "")
                        if text:
                            await client_ws.send_json({
                                "type": "text",
                                "text": text,
                                "role": "assistant"
                            })
                    else:
                        logger.info(f"Output item type '{item_type}' not handled, full item: {json.dumps(item)[:300]}")
                
                elif event_type == "response.text.delta":
                    # Text delta from OpenAI
                    await client_ws.send_json({
                        "type": "text",
                        "text": data.get("delta", ""),
                        "role": "assistant"
                    })
                
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # User transcription
                    item = data.get("item", {})
                    transcript = item.get("transcript", "")
                    if transcript:
                        await client_ws.send_json({
                            "type": "text",
                            "text": transcript,
                            "role": "user"
                        })
                        logger.info(f"User transcript: {transcript}")
                
                elif event_type == "conversation.item.created":
                    # Handle conversation items (transcripts, function calls, etc.)
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
                            logger.info(f"User transcript: {transcript}")
                    # Could handle other item types here (function calls, etc.)
                
                elif event_type == "response.created":
                    # Response object was created
                    logger.info("Response created - checking status")
                    response_obj = data.get("response", {})
                    if isinstance(response_obj, dict):
                        response_id = response_obj.get("id")
                        response_status = response_obj.get("status")
                        logger.info(f"Response ID: {response_id}, Status: {response_status}")
                        # Log all response fields
                        logger.info(f"Response fields: {list(response_obj.keys())}")
                    # Forward to client
                    await client_ws.send_json({"type": "response.created"})
                
                elif event_type == "response.started":
                    await client_ws.send_json({"type": "response.started"})
                    logger.info("Response started - expecting audio/text deltas")
                    # Log response details
                    response_id = data.get("response", {}).get("id") if isinstance(data.get("response"), dict) else None
                    if response_id:
                        logger.info(f"Response ID: {response_id}")
                
                elif event_type == "response.done":
                    await client_ws.send_json({"type": "response.done"})
                    logger.info("✅ Response done")
                    # Log response details to see why no audio
                    response_obj = data.get("response", {})
                    if isinstance(response_obj, dict):
                        response_status = response_obj.get("status")
                        output_items = response_obj.get("output", [])
                        logger.info(f"   Response status: {response_status}")
                        logger.info(f"   Response keys: {list(response_obj.keys())}")
                        logger.info(f"   Output items count: {len(output_items) if output_items else 0}")
                        if output_items:
                            for idx, item in enumerate(output_items):
                                item_type = item.get("type")
                                logger.info(f"   Output item {idx}: type={item_type}, keys={list(item.keys())}")
                                # Check if audio is in the output items
                                if item_type == "audio":
                                    audio_data = item.get("audio", "")
                                    if audio_data:
                                        logger.info(f"   🎵 Found audio in output item {idx} ({len(audio_data)} chars)")
                                        # Send it to client!
                                        await client_ws.send_json({
                                            "type": "audio",
                                            "data": audio_data
                                        })
                                    else:
                                        logger.warning(f"   ⚠️ Audio item {idx} has no audio data")
                        else:
                            logger.warning("   ⚠️ No output items in response.done - response may have failed")
                    # Also log full event for debugging
                    logger.debug(f"   Full response.done event: {json.dumps(data)[:500]}")
                
                elif event_type == "response.interrupted":
                    await client_ws.send_json({"type": "interrupted"})
                    logger.info("🛑 Response interrupted by user")
                
                elif event_type == "input_audio_buffer.speech_started":
                    await client_ws.send_json({"type": "speech_started"})
                    logger.info("User started speaking - this will interrupt assistant if speaking")
                
                elif event_type == "input_audio_buffer.speech_stopped":
                    await client_ws.send_json({"type": "speech_stopped"})
                    logger.info("User stopped speaking - OpenAI should trigger response automatically")
                
                elif event_type == "input_audio_buffer.committed":
                    logger.info("Input audio buffer committed")
                    await client_ws.send_json({"type": "input_audio_buffer.committed"})
                
                elif event_type == "output_audio_buffer.started":
                    logger.info("🎵 Output audio buffer started - audio streaming beginning")
                    await client_ws.send_json({"type": "output_audio_buffer.started"})
                
                elif event_type == "output_audio_buffer.speech_started":
                    logger.info("🎵 Assistant started speaking (audio output)")
                    await client_ws.send_json({"type": "output_audio_buffer.speech_started"})
                
                elif event_type == "output_audio_buffer.speech_stopped":
                    logger.info("🎵 Assistant stopped speaking (audio output)")
                    await client_ws.send_json({"type": "output_audio_buffer.speech_stopped"})
                
                elif event_type == "output_audio_buffer.interrupted":
                    logger.info("🛑 Output audio buffer interrupted - user spoke during assistant response")
                    await client_ws.send_json({"type": "interrupted"})
                
                elif event_type == "error":
                    await client_ws.send_json({
                        "type": "error",
                        "error": str(data)
                    })
                    logger.error(f"OpenAI Error: {data}")
                
                elif event_type == "session.created":
                    logger.info("OpenAI session created")
                    # Optionally send confirmation to client
                    await client_ws.send_json({"type": "session.created"})
                
                else:
                    # Forward unknown events as-is (for debugging)
                    logger.info(f"Received unknown/unhandled event: {event_type}")
                    # Log full data for debugging (truncated)
                    event_preview = json.dumps(data)[:500]
                    logger.info(f"Event data preview: {event_preview}")
                    # Still forward to client in case frontend can handle it
                    await client_ws.send_json(data)
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"OpenAI WebSocket disconnected: {e}")
            # Notify client of OpenAI disconnection
            try:
                await client_ws.send_json({
                    "type": "error",
                    "error": "OpenAI connection closed",
                    "error_type": "openai_disconnected"
                })
            except:
                pass  # Client may already be disconnected
        except Exception as e:
            logger.error(f"Error in vendor_to_client: {e}")
            traceback.print_exc()
            # Try to send error to client if still connected
            try:
                await client_ws.send_json({
                    "type": "error",
                    "error": f"Error processing OpenAI message: {str(e)}",
                    "error_type": "vendor_to_client_error"
                })
            except:
                pass  # Client may already be disconnected
    
    # Run both relay tasks concurrently
    # vendor_to_client will handle server.hello and send session config
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections from clients."""
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"Client connected: {client_ip}")
    
    await websocket.accept()
    
    if not OPENAI_API_KEY:
        error_msg = "OPENAI_API_KEY not set"
        logger.error(error_msg)
        await send_error_safe(websocket, "config_error", error_msg)
        await websocket.close(code=1008, reason=error_msg)
        return
    
    try:
        # Connect to OpenAI Realtime API
        async with websockets.connect(
            OPENAI_REALTIME_URL,
            extra_headers=get_openai_headers(),
        ) as vendor_ws:
            logger.info("Connected to OpenAI Realtime API")
            
            # Start bidirectional relay (session config sent after server.hello)
            await relay_messages(websocket, vendor_ws)
            
    except websockets.exceptions.InvalidHandshake as e:
        error_msg = f"OpenAI WebSocket handshake failed: {e}"
        logger.error(error_msg)
        await send_error_safe(websocket, "handshake_error", error_msg)
        await websocket.close(code=1011)
        
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {client_ip}")
        
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(error_msg)
        traceback.print_exc()
        try:
            await send_error_safe(websocket, "unexpected_error", error_msg)
        except:
            pass
        try:
            await websocket.close()
        except:
            pass
