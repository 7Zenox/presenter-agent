"""WebSocket endpoint for live presentation."""
import json
import base64
import uuid
import asyncio
import os
import time
from typing import Dict, Optional
from dotenv import load_dotenv
from fastapi import WebSocket, WebSocketDisconnect
from app.schemas import (
    ClientConfig, ClientUploadPPT, ClientAudio, ClientInterrupt,
    ServerReady, ServerTranscript, ServerAudio, ServerEnd
)
from app.ppt_parser import parse_powerpoint_from_base64
from app.live_api import LiveAPISession
# Audio conversion no longer needed - frontend sends PCM16 directly via AudioWorklet

# Load environment variables
load_dotenv()


class WebSocketManager:
    """Manages WebSocket connections and sessions."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.session_data: Dict[str, Dict] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection."""
        await websocket.accept()
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        """Remove a WebSocket connection."""
        self.active_connections.pop(session_id, None)
        self.session_data.pop(session_id, None)
    
    async def send_json(self, session_id: str, data: dict):
        """Send JSON message to a session."""
        if session_id in self.active_connections:
            # Check if connection is still active
            session_data = self.session_data.get(session_id, {})
            if not session_data.get("_connection_active", True):
                # Connection is closed, don't try to send
                return
            
            try:
                await self.active_connections[session_id].send_json(data)
            except Exception as e:
                print(f"[WebSocket] Error sending message to {session_id}: {e}")
                # Mark connection as inactive
                if session_id in self.session_data:
                    self.session_data[session_id]["_connection_active"] = False


ws_manager = WebSocketManager()


async def handle_client_config(websocket: WebSocket, session_id: str, config: ClientConfig):
    """Handle client configuration (legacy, kept for compatibility)."""
    await ws_manager.send_json(session_id, {
        "type": "SERVER_ERROR",
        "message": "Please upload a PowerPoint file using CLIENT_UPLOAD_PPT instead"
    })


async def handle_client_upload_ppt(websocket: WebSocket, session_id: str, upload: ClientUploadPPT):
    """Handle PowerPoint file upload and initialize session."""
    try:
        # Parse PowerPoint file
        slides = parse_powerpoint_from_base64(upload.data)
        
        if not slides:
            raise Exception("No slides found in PowerPoint file")
        
        # Use filename or topic as presentation name
        topic = upload.topic or upload.filename.replace(".pptx", "").replace(".ppt", "")
        
        # Build presentation content - all slides as context
        presentation_content = f"Presentation: {topic}\n\n"
        for i, slide in enumerate(slides, 1):
            presentation_content += f"Slide {i}: {slide.title}\n"
            if slide.bullets:
                for bullet in slide.bullets:
                    presentation_content += f"  - {bullet}\n"
            presentation_content += "\n"
        
        # Create Live API session with all presentation content
        live_session = LiveAPISession(session_id, presentation_content)
        
        # Set up callbacks for audio and text
        async def on_audio_received(audio_data: bytes):
            """Callback when audio is received from Live API."""
            # Track when AI audio is received (for interruption detection)
            session_data = ws_manager.session_data.get(session_id)
            if session_data:
                session_data["_last_ai_audio_time"] = time.time()
            
            # Encode audio to base64 and send to frontend
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            await ws_manager.send_json(session_id, ServerAudio(
                data=audio_base64,
                sequence=0
            ).model_dump())
        
        async def on_text_received(text: str):
            """Callback when text is received from Live API."""
            await ws_manager.send_json(session_id, ServerTranscript(
                role="assistant",
                text=text,
                final=False
            ).model_dump())
        
        async def on_user_turn_detected():
            """Callback when user turn is detected by Live API VAD."""
            print(f"[WebSocket] 🛑 User turn detected - sending interrupt signal to frontend")
            # Send interrupt message to frontend to stop playback
            await ws_manager.send_json(session_id, {
                "type": "SERVER_INTERRUPT"
            })
        
        live_session.on_audio_callback = on_audio_received
        live_session.on_text_callback = on_text_received
        live_session.on_user_turn_callback = on_user_turn_detected
        
        # Start Live API session
        await live_session.start()
        
        # Store session data (simplified - no managers)
        ws_manager.session_data[session_id] = {
            "topic": topic,
            "filename": upload.filename,
            "live_session": live_session,
            "slides": slides  # Keep slides for frontend display
        }
        
        # Send ready message
        await ws_manager.send_json(session_id, ServerReady(sessionId=session_id).model_dump())
        
        # Send slides data to frontend (for display only)
        await ws_manager.send_json(session_id, {
            "type": "SERVER_SLIDES",
            "slides": [
                {
                    "id": slide.id,
                    "title": slide.title,
                    "bullets": slide.bullets
                }
                for slide in slides
            ]
        })
        
        # Send initial prompt to start conversation
        prompt = f"Hello! I've uploaded a presentation about '{topic}'. Please introduce it and we can discuss it together. Start speaking now."
        if live_session.live_session:
            print(f"[WebSocket] 📤 Sending initial prompt to Live API: {prompt[:100]}...")
            try:
                await live_session.live_session.send_realtime_input(text=prompt)
                print(f"[WebSocket] ✅ Initial prompt sent successfully, waiting for audio response...")
            except Exception as e:
                print(f"[WebSocket] ✗ Error sending initial prompt: {e}")
                import traceback
                traceback.print_exc()
        
    except Exception as e:
        await ws_manager.send_json(session_id, {
            "type": "SERVER_ERROR",
            "message": str(e)
        })


async def handle_client_audio(websocket: WebSocket, session_id: str, audio: ClientAudio):
    """Handle client audio chunks and forward to Live API."""
    session_data = ws_manager.session_data.get(session_id)
    if not session_data:
        print(f"[WebSocket] ⚠️ No session data found for {session_id} when handling audio")
        return
    
    live_session = session_data.get("live_session")
    if not live_session:
        print(f"[WebSocket] ⚠️ No Live API session found for {session_id} when handling audio")
        return
    
    # Decode audio from base64
    try:
        # DEBUG: Track chunk count
        audio_chunk_count = session_data.get("_audio_chunk_count", 0) + 1
        session_data["_audio_chunk_count"] = audio_chunk_count
        should_log = audio_chunk_count <= 20 or audio_chunk_count % 10 == 0
        
        if should_log:
            print(f"[WebSocket] 📥 Received CLIENT_AUDIO chunk #{audio_chunk_count}: {len(audio.data)} chars base64")
        
        # Frontend now sends PCM16 directly (via AudioWorklet), not WebM
        pcm_data = base64.b64decode(audio.data)
        
        if should_log:
            print(f"[WebSocket] 📦 Decoded PCM16: {len(pcm_data)} bytes")
        
        # Skip empty chunks
        if len(pcm_data) == 0:
            if should_log:
                print(f"[WebSocket] ⚠️ Empty PCM chunk, skipping")
            return
        
        # Validate PCM16 format (should be even number of bytes, 16-bit = 2 bytes per sample)
        if len(pcm_data) % 2 != 0:
            print(f"[WebSocket] ⚠️ Invalid PCM16 data: odd number of bytes ({len(pcm_data)})")
            return
        
        if should_log:
            # Calculate duration: PCM 16-bit mono at 16kHz = 2 bytes per sample
            # Duration = (bytes / 2) / sample_rate seconds
            duration_ms = (len(pcm_data) / 2) / 16000 * 1000
            print(f"[WebSocket] ✅ Received PCM16: {len(pcm_data)} bytes, duration: {duration_ms:.1f}ms")
        
        # ADK Pattern: Send ALL audio continuously to Live API
        # Live API's built-in VAD will automatically detect speech and handle interruptions
        # No need for custom interrupt logic - just send everything
        if should_log:
            print(f"[WebSocket] 📤 Sending audio to Live API (VAD will handle speech detection)")
        
        # Simply queue the audio - the upstream task will send it
        await live_session.send_audio(pcm_data, interrupt=False)
            
        if should_log:
            print(f"[WebSocket] ✅ Audio chunk #{audio_chunk_count} processed successfully")
            
    except Exception as e:
        print(f"[WebSocket] ✗ Error processing audio: {e}")
        import traceback
        traceback.print_exc()
        # Don't send error to client for audio processing errors to avoid spam
        # Just log and continue


# Removed: auto_start_presentation - not needed with simplified flow


async def handle_client_interrupt(websocket: WebSocket, session_id: str):
    """Handle client interrupt."""
    session_data = ws_manager.session_data.get(session_id)
    if not session_data:
        print(f"[WebSocket] ⚠️ No session data found for {session_id} when handling interrupt")
        return
    
    live_session = session_data.get("live_session")
    if live_session:
        print(f"[WebSocket] 🛑 Interrupting Live API session for {session_id}")
        # Interrupt Live API session - clear audio queues
        await live_session.interrupt()
        # Mark that we're interrupting so subsequent audio chunks know
        session_data["_interrupting"] = True
    else:
        print(f"[WebSocket] ⚠️ No Live API session found for {session_id} when handling interrupt")


# Removed: handle_client_control - no slide navigation in simplified flow


# Removed: process_user_text - use audio input via Live API instead
# If text input is needed, send it directly to Live API session via send_realtime_input(text=...)


async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint."""
    session_id = str(uuid.uuid4())
    connection_active = True
    
    try:
        await ws_manager.connect(websocket, session_id)
        print(f"[WebSocket] ✅ Client connected, session_id: {session_id}")
        
        # Initialize session data for tracking
        ws_manager.session_data[session_id] = ws_manager.session_data.get(session_id, {})
        session_data = ws_manager.session_data[session_id]
        session_data["_connection_active"] = True
        
        while connection_active:
            try:
                # Receive message
                data = await websocket.receive_json()
                msg_type = data.get("type")
                
                # Log all message types for debugging - throttle audio messages
                if msg_type == "CLIENT_AUDIO":
                    # Track audio message count
                    if "_ws_audio_msg_count" not in session_data:
                        session_data["_ws_audio_msg_count"] = 0
                    session_data["_ws_audio_msg_count"] += 1
                    audio_count = session_data["_ws_audio_msg_count"]
                    if audio_count <= 5 or audio_count % 50 == 0:
                        data_size = len(data.get("data", "")) if isinstance(data.get("data"), str) else 0
                        print(f"[WebSocket] 📨 Received CLIENT_AUDIO message #{audio_count}, data size: {data_size} chars")
                else:
                    print(f"[WebSocket] 📨 Received message type: {msg_type}")
                
                if msg_type == "CLIENT_CONFIG":
                    await handle_client_config(websocket, session_id, ClientConfig(**data))
                elif msg_type == "CLIENT_UPLOAD_PPT":
                    await handle_client_upload_ppt(websocket, session_id, ClientUploadPPT(**data))
                elif msg_type == "CLIENT_AUDIO":
                    await handle_client_audio(websocket, session_id, ClientAudio(**data))
                elif msg_type == "CLIENT_INTERRUPT":
                    await handle_client_interrupt(websocket, session_id)
                # Removed: CLIENT_CONTROL and CLIENT_TEXT - simplified to audio-only flow
                else:
                    await ws_manager.send_json(session_id, {
                        "type": "SERVER_ERROR",
                        "message": f"Unknown message type: {msg_type}"
                    })
            except WebSocketDisconnect:
                # Client disconnected, exit loop
                connection_active = False
                session_data["_connection_active"] = False
                break
            except RuntimeError as re:
                if "Cannot call \"receive\" once a disconnect message has been received" in str(re):
                    # WebSocket already disconnected
                    print(f"[WebSocket] Connection already closed for {session_id}")
                    connection_active = False
                    session_data["_connection_active"] = False
                    break
                else:
                    raise
            except Exception as msg_error:
                print(f"[WebSocket] ✗ Error handling message: {msg_error}")
                import traceback
                traceback.print_exc()
                # Try to send error to client
                try:
                    if connection_active:
                        await ws_manager.send_json(session_id, {
                            "type": "SERVER_ERROR",
                            "message": f"Error processing message: {str(msg_error)}"
                        })
                except:
                    # If we can't send, connection might be broken
                    connection_active = False
                    session_data["_connection_active"] = False
                    break
    
    except WebSocketDisconnect:
        # Cleanup
        print(f"[WebSocket] Client disconnected: {session_id}")
        session_data = ws_manager.session_data.get(session_id)
        if session_data:
            live_session = session_data.get("live_session")
            if live_session:
                try:
                    await live_session.stop()
                except Exception as e:
                    print(f"[WebSocket] Error stopping Live API session: {e}")
        # Removed: memory_manager cleanup - not used in simplified flow
        ws_manager.disconnect(session_id)
    except Exception as e:
        print(f"[WebSocket] Error in WebSocket handler: {e}")
        import traceback
        traceback.print_exc()
        try:
            await ws_manager.send_json(session_id, {
                "type": "SERVER_ERROR",
                "message": f"WebSocket error: {str(e)}"
            })
        except:
            pass  # Connection might already be closed
        session_data = ws_manager.session_data.get(session_id)
        if session_data:
            live_session = session_data.get("live_session")
            if live_session:
                try:
                    await live_session.stop()
                except:
                    pass
        # Removed: unregister_session - not needed in simplified flow
        ws_manager.disconnect(session_id)

