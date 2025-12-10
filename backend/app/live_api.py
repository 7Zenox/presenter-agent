"""Gemini Live API integration for bidirectional voice streaming."""
import asyncio
import base64
from typing import Optional, Callable, Awaitable
from google import genai
from app.gemini_client import get_client


# Live API model - using gemini-2.0-flash-exp (experimental Live API model)
# This is the correct model name for Live API as used in the official web console
LIVE_MODEL = "gemini-2.0-flash-exp"

# Audio configuration
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000


class LiveAPISession:
    """Manages a Gemini Live API session with WebSocket integration."""
    
    def __init__(self, session_id: str, presentation_content: str):
        self.session_id = session_id
        self.presentation_content = presentation_content
        self.client = get_client()
        self.live_session: Optional[genai.aio.live.LiveSession] = None
        self._context_manager = None  # Keep reference to context manager for cleanup
        self.audio_queue_output = asyncio.Queue()
        self.audio_queue_input = asyncio.Queue(maxsize=10)
        self.is_running = False
        self.on_audio_callback: Optional[Callable[[bytes], Awaitable[None]]] = None
        self.on_text_callback: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_user_turn_callback: Optional[Callable[[], Awaitable[None]]] = None  # Callback when user turn detected
        self._pause_audio_until: Optional[float] = None  # Timestamp when to resume audio sending after interruption
        self._last_interruption_response: int = 0  # Response number when interruption was detected
        self._turn_complete_response: int = 0  # Response number when turn_complete was detected after interruption
        
    async def start(self):
        """Start the Live API session."""
        from google.genai import types
        
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": f"""You are a helpful assistant discussing a presentation with the user.

Here is the presentation content:

{self.presentation_content}

You can discuss any part of the presentation, answer questions about it, and have a natural conversation.
Speak naturally and conversationally.
""",
            # Enable automatic Voice Activity Detection (VAD)
            # This will automatically detect when user starts/stops speaking
            # and handle interruptions more reliably than our custom frontend logic
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,  # Enable automatic VAD
                    # Use HIGH sensitivity for better speech detection
                    # LOW was too conservative and might miss user speech
                    "start_of_speech_sensitivity": types.StartSensitivity.START_SENSITIVITY_HIGH,
                    "end_of_speech_sensitivity": types.EndSensitivity.END_SENSITIVITY_HIGH,
                    "prefix_padding_ms": 50,  # Increased padding to capture speech start
                    "silence_duration_ms": 50,  # Reduced from 100ms to 50ms for faster end-of-speech detection
                    # This allows Live API to process user speech faster after interruption
                    # Lower value = more responsive to end-of-speech, allowing Live API to process user input sooner
                    # Note: According to docs, this is "The required duration of detected silence before end-of-speech is committed"
                    # Very low values may cause false end-of-speech detection during natural pauses, but improve responsiveness
                }
                # Note: activity_handling is not available in Python SDK's LiveConnectConfig
                # According to docs, START_OF_ACTIVITY_INTERRUPTS is the default behavior
                # So interruptions should work by default with automatic_activity_detection enabled
            }
        }
        
        # Enter the async context manager
        context_manager = self.client.aio.live.connect(
            model=LIVE_MODEL,
            config=config
        )
        self.live_session = await context_manager.__aenter__()
        self._context_manager = context_manager  # Keep reference for cleanup
        
        self.is_running = True
        
        print(f"[LiveAPI] ✅ Session started for {self.session_id}")
        print(f"[LiveAPI] 📋 Presentation content length: {len(self.presentation_content)} chars")
        print(f"[LiveAPI] 🎤 VAD enabled: automatic_activity_detection.disabled=False")
        print(f"[LiveAPI] 🔧 Start sensitivity: START_SENSITIVITY_HIGH (more sensitive to detect speech)")
        print(f"[LiveAPI] 🔧 End sensitivity: END_SENSITIVITY_HIGH")
        print(f"[LiveAPI] 🛑 Activity handling: START_OF_ACTIVITY_INTERRUPTS (default - barge-in enabled)")
        
        # Start background tasks
        print(f"[LiveAPI] 🚀 Starting background tasks: _send_audio_to_live() and _receive_from_live()")
        asyncio.create_task(self._send_audio_to_live())
        asyncio.create_task(self._receive_from_live())
        
    async def _send_audio_to_live(self):
        """Send audio chunks from queue to Live API."""
        while self.is_running:
            try:
                # Check if we should pause audio sending after interruption
                # This allows Live API to detect end-of-speech (silence) and process user speech
                if self._pause_audio_until is not None:
                    import time
                    current_time = time.time()
                    if current_time < self._pause_audio_until:
                        # Still in pause period - drop this audio chunk to create silence
                        try:
                            audio_data = await asyncio.wait_for(self.audio_queue_input.get(), timeout=0.1)
                            # Drop the chunk - don't send it to Live API
                            if not hasattr(self, '_dropped_chunk_count'):
                                self._dropped_chunk_count = 0
                            self._dropped_chunk_count += 1
                            if self._dropped_chunk_count <= 5:
                                print(f"[LiveAPI] ⏸️ Pausing audio sending (dropped chunk #{self._dropped_chunk_count}) to allow end-of-speech detection")
                            continue
                        except asyncio.TimeoutError:
                            # No audio available - continue waiting
                            continue
                    else:
                        # Pause period ended (timeout) - resume sending even if input_transcription hasn't appeared
                        print(f"[LiveAPI] ⏰ Pause timeout reached - resuming audio sending")
                        print(f"[LiveAPI] ⚠️ Note: input_transcription may not have appeared yet, but resuming to prevent infinite pause")
                        self._pause_audio_until = None
                
                audio_data = await asyncio.wait_for(self.audio_queue_input.get(), timeout=1.0)
                if self.live_session:
                    # DEBUG: Track sent chunks
                    if not hasattr(self, '_sent_log_count'):
                        self._sent_log_count = 0
                    self._sent_log_count += 1
                    should_log = self._sent_log_count <= 20 or self._sent_log_count % 10 == 0
                    
                    if should_log:
                        print(f"[LiveAPI] 📤 Sending audio chunk #{self._sent_log_count} to Live API: {len(audio_data)} bytes PCM")
                    
                    # Send audio chunk to Live API
                    # Live API's built-in VAD will handle interruption automatically
                    try:
                        # Calculate audio duration for logging
                        duration_ms = (len(audio_data) / 2) / 16000 * 1000
                        await self.live_session.send_realtime_input(
                            audio={"data": audio_data, "mime_type": "audio/pcm;rate=16000"}
                        )
                        if should_log:
                            print(f"[LiveAPI] ✅ Successfully sent chunk #{self._sent_log_count} to Live API: {len(audio_data)} bytes PCM ({duration_ms:.1f}ms)")
                    except Exception as e:
                        print(f"[LiveAPI] ✗ Error sending audio to Live API: {e}")
                        import traceback
                        traceback.print_exc()
            except asyncio.TimeoutError:
                # No audio for a while - this is normal, just continue
                continue
            except Exception as e:
                print(f"[LiveAPI] ✗ Error in _send_audio_to_live: {e}")
                import traceback
                traceback.print_exc()
                break
    
    async def _receive_from_live(self):
        """Receive responses from Live API."""
        if not self.live_session:
            print(f"[LiveAPI] ⚠️ No live_session available for receive loop")
            return
            
        try:
            print(f"[LiveAPI] 🎧 Starting receive loop for session {self.session_id}")
            response_count = 0
            audio_chunk_count = 0
            text_chunk_count = 0
            
            while self.is_running:
                # receive() returns an async iterator, iterate it directly
                async for response in self.live_session.receive():
                    response_count += 1
                    should_log_response = response_count <= 50 or response_count % 20 == 0
                    
                    # DEBUG: Log ALL response types to understand what Live API is sending
                    # Check what type of response this is
                    response_type = "unknown"
                    response_details = []
                    
                    # FIRST: Check response object itself for interrupted (might be at top level)
                    if hasattr(response, 'interrupted'):
                        interrupted_at_response_level = getattr(response, 'interrupted', None)
                        if interrupted_at_response_level:
                            print(f"[LiveAPI] 🛑🛑🛑 INTERRUPTED AT RESPONSE LEVEL! Response #{response_count}, value={interrupted_at_response_level} 🛑🛑🛑")
                            # Clear audio queue and trigger callback
                            cleared_count = 0
                            while not self.audio_queue_output.empty():
                                try:
                                    self.audio_queue_output.get_nowait()
                                    cleared_count += 1
                                except asyncio.QueueEmpty:
                                    break
                            if cleared_count > 0:
                                print(f"[LiveAPI] 🛑 Cleared {cleared_count} pending AI audio chunks from queue")
                            if self.on_user_turn_callback:
                                await self.on_user_turn_callback()
                            continue
                    
                    # REFERENCE IMPLEMENTATION PATTERN:
                    # Check for "interrupted" key FIRST, return immediately if found
                    # This matches: if ("interrupted" in serverContent) { emit("interrupted"); return; }
                    if hasattr(response, 'server_content') and response.server_content:
                        server_content = response.server_content
                        
                        # DEBUG: Log structure of EVERY response to understand what we're getting
                        # ALWAYS log detailed info for first 100 responses, then every 10th
                        # ALSO log ALL responses after interruption (to track user_turn)
                        if not hasattr(self, '_last_interruption_response'):
                            self._last_interruption_response = 0
                        
                        should_log_detailed = (
                            response_count <= 100 or 
                            response_count % 10 == 0 or
                            (self._last_interruption_response > 0 and response_count - self._last_interruption_response <= 30)
                        )
                        if should_log_detailed:
                            print(f"[LiveAPI] 🔍 Response #{response_count} server_content type: {type(server_content)}")
                            
                            # Try to convert to dict to check for keys (like reference implementation)
                            try:
                                if hasattr(server_content, 'to_dict'):
                                    sc_dict = server_content.to_dict()
                                    print(f"[LiveAPI] 🔍   ✅ to_dict() SUCCESS! keys: {list(sc_dict.keys())}")
                                    # Check for ALL possible interruption-related keys
                                    for key in ['interrupted', 'interrupt', 'user_turn', 'userTurn', 'turn_complete', 'turnComplete']:
                                        if key in sc_dict:
                                            print(f"[LiveAPI] 🔍   ⚠️⚠️⚠️ FOUND '{key}' KEY IN to_dict(): {sc_dict[key]} (type: {type(sc_dict[key])}) ⚠️⚠️⚠️")
                                else:
                                    print(f"[LiveAPI] 🔍   ❌ No to_dict() method on server_content")
                            except Exception as e:
                                print(f"[LiveAPI] 🔍   ❌ Could not convert to_dict(): {type(e).__name__}: {e}")
                            
                            # Also log all attributes - ALWAYS for first 50 responses
                            if response_count <= 50:
                                attrs = [a for a in dir(server_content) if not a.startswith('_')]
                                print(f"[LiveAPI] 🔍   Available attributes ({len(attrs)}): {attrs[:25]}")
                                # Check each attribute value
                                for attr in ['interrupted', 'interrupt', 'user_turn', 'userTurn', 'model_turn', 'modelTurn', 'turn_complete', 'turnComplete']:
                                    if hasattr(server_content, attr):
                                        try:
                                            val = getattr(server_content, attr)
                                            print(f"[LiveAPI] 🔍   ✅ {attr} = {val} (type: {type(val)})")
                                        except Exception as e:
                                            print(f"[LiveAPI] 🔍   ❌ {attr} exists but error accessing: {type(e).__name__}: {e}")
                                    else:
                                        if response_count <= 20:  # Only log missing attrs for first 20
                                            print(f"[LiveAPI] 🔍   ❌ {attr} attribute NOT FOUND")
                        
                        # Check for interrupted key existence (like reference: "interrupted" in serverContent)
                        interrupted_detected = False
                        
                        # Method 1: Try using model_dump() (Pydantic method) to convert to dict
                        try:
                            if hasattr(server_content, 'model_dump'):
                                sc_dict = server_content.model_dump()
                                # Log full structure for first 10 responses AND after interruption
                                # Track if we've had an interruption to log subsequent responses
                                if not hasattr(self, '_last_interruption_response'):
                                    self._last_interruption_response = 0
                                
                                should_log_dict = (
                                    response_count <= 10 or 
                                    response_count - self._last_interruption_response <= 20
                                )
                                
                                if should_log_dict:
                                    print(f"[LiveAPI] 🔍   model_dump() keys: {list(sc_dict.keys())}")
                                    for key in ['interrupted', 'user_turn', 'turn_complete', 'generation_complete', 'input_transcription', 'waiting_for_input', 'output_transcription']:
                                        if key in sc_dict:
                                            val = sc_dict[key]
                                            print(f"[LiveAPI] 🔍   model_dump()[{key}] = {val} (type: {type(val)})")
                                
                                # Check for interrupted
                                if 'interrupted' in sc_dict and sc_dict['interrupted'] is True:
                                    interrupted_detected = True
                                    self._last_interruption_response = response_count
                                    print(f"[LiveAPI] 🛑🛑🛑 INTERRUPTED KEY FOUND IN model_dump()! Response #{response_count} 🛑🛑🛑")
                                
                                # IMPORTANT: Check for user_turn AFTER interruption
                                # This is what Live API sends when it detects user speech
                                if 'user_turn' in sc_dict and sc_dict['user_turn']:
                                    print(f"[LiveAPI] 🎤🎤🎤 USER_TURN FOUND IN model_dump()! Response #{response_count} 🎤🎤🎤")
                                    print(f"[LiveAPI] 🎤 user_turn value: {sc_dict['user_turn']}")
                                
                                # Check waiting_for_input - indicates Live API is waiting for user speech to complete
                                if 'waiting_for_input' in sc_dict:
                                    waiting_val = sc_dict['waiting_for_input']
                                    if waiting_val:
                                        print(f"[LiveAPI] ⏳ waiting_for_input = {waiting_val} (Live API waiting for user speech to complete)")
                                
                                # Check output_transcription - might contain user speech transcription
                                if 'output_transcription' in sc_dict and sc_dict['output_transcription']:
                                    output_trans = sc_dict['output_transcription']
                                    print(f"[LiveAPI] 📝 output_transcription found: {str(output_trans)[:200]}...")
                        except Exception as e:
                            if response_count <= 10:
                                print(f"[LiveAPI] 🔍   model_dump() error: {type(e).__name__}: {e}")
                        
                        # Method 2: Try using dict() method (Pydantic)
                        if not interrupted_detected:
                            try:
                                if hasattr(server_content, 'dict'):
                                    sc_dict = server_content.dict()
                                    if 'interrupted' in sc_dict and sc_dict['interrupted'] is True:
                                        interrupted_detected = True
                                        print(f"[LiveAPI] 🛑🛑🛑 INTERRUPTED KEY FOUND IN dict()! Response #{response_count}, value={sc_dict['interrupted']} 🛑🛑🛑")
                            except Exception as e:
                                if response_count <= 10:
                                    print(f"[LiveAPI] 🔍   dict() error: {e}")
                        
                        # Method 3: Check if it's already a dict and has 'interrupted' key
                        if not interrupted_detected and isinstance(server_content, dict):
                            if 'interrupted' in server_content and server_content['interrupted'] is True:
                                interrupted_detected = True
                                print(f"[LiveAPI] 🛑🛑🛑 INTERRUPTED KEY FOUND IN DICT! Response #{response_count}, value={server_content['interrupted']} 🛑🛑🛑")
                        
                        # Method 4: Check attribute directly (we know it exists but is None)
                        # CRITICAL: Only trigger if it's explicitly True, not just if attribute exists
                        if not interrupted_detected and hasattr(server_content, 'interrupted'):
                            interrupted_value = getattr(server_content, 'interrupted', None)
                            # Only trigger if it's explicitly True
                            if interrupted_value is True:
                                interrupted_detected = True
                                print(f"[LiveAPI] 🛑🛑🛑 INTERRUPTED ATTRIBUTE IS TRUE! Response #{response_count} 🛑🛑🛑")
                        
                        # Method 5: Check input_transcription - if it exists and has content, user spoke
                        # This might indicate user speech was detected even if interrupted flag wasn't set
                        # Also log input_transcription even if we've already detected interruption (for debugging)
                        if hasattr(server_content, 'input_transcription'):
                            input_transcription = getattr(server_content, 'input_transcription', None)
                            if input_transcription and len(str(input_transcription).strip()) > 0:
                                if not interrupted_detected:
                                    print(f"[LiveAPI] 🎤 Input transcription detected (user spoke): {str(input_transcription)[:100]}...")
                                    # This indicates user speech was detected - trigger interrupt
                                    interrupted_detected = True
                                    print(f"[LiveAPI] 🛑 Triggering interrupt based on input_transcription (user speech detected)")
                                else:
                                    # Already detected interruption, but log transcription for debugging
                                    print(f"[LiveAPI] 🎤 Input transcription in interrupted response: {str(input_transcription)[:100]}...")
                        
                        # CRITICAL: If interrupted, handle it and RETURN (like reference implementation)
                        if interrupted_detected:
                            response_type = "interrupted"
                            # Clear output audio queue immediately (AI audio)
                            cleared_output_count = 0
                            while not self.audio_queue_output.empty():
                                try:
                                    self.audio_queue_output.get_nowait()
                                    cleared_output_count += 1
                                except asyncio.QueueEmpty:
                                    break
                            if cleared_output_count > 0:
                                print(f"[LiveAPI] 🛑 Cleared {cleared_output_count} pending AI audio chunks from output queue")
                            
                            # CRITICAL: Clear input audio queue to prevent buffered user audio from being sent
                            # This ensures Live API gets a clean silence period to detect end-of-speech
                            cleared_input_count = 0
                            while not self.audio_queue_input.empty():
                                try:
                                    self.audio_queue_input.get_nowait()
                                    cleared_input_count += 1
                                except asyncio.QueueEmpty:
                                    break
                            if cleared_input_count > 0:
                                print(f"[LiveAPI] 🛑 Cleared {cleared_input_count} buffered user audio chunks from input queue")
                                print(f"[LiveAPI] ⚠️ This ensures Live API gets a clean silence period to detect end-of-speech")
                            
                            # CRITICAL: Pause audio sending until input_transcription appears
                            # Live API needs silence (end-of-speech detection) before it can process user speech
                            # We'll keep pausing until Live API processes user speech (indicated by input_transcription)
                            # IMPORTANT: Keep pausing until input_transcription appears to give Live API the silence it needs
                            import time
                            # Set pause to 2 seconds - this gives Live API time to detect end-of-speech if user pauses
                            # After 2 seconds, resume sending audio so Live API can process the user's speech
                            # The pause is just to clear any buffered audio and give Live API a moment to detect end-of-speech
                            self._pause_audio_until = time.time() + 2.0  # 2 seconds pause
                            print(f"[LiveAPI] ⏸️ Pausing audio sending for 2 seconds to allow end-of-speech detection")
                            print(f"[LiveAPI] ⚠️ This pause allows Live API to detect end-of-speech and process user speech")
                            print(f"[LiveAPI] ⚠️ Audio sending will resume after 2 seconds OR when input_transcription appears")
                            print(f"[LiveAPI] ⚠️ After pause, Live API should process user speech even if user is still speaking")
                            
                            # Track interruption response number
                            self._last_interruption_response = response_count
                            self._turn_complete_response = 0  # Reset turn_complete tracking
                            
                            # Trigger callback
                            if self.on_user_turn_callback:
                                print(f"[LiveAPI] 🛑 Calling interrupt callback")
                                await self.on_user_turn_callback()
                            # Log that we're expecting user_turn next
                            print(f"[LiveAPI] 🔄 After interruption, expecting user_turn response with user speech transcription")
                            print(f"[LiveAPI] 🔄 Live API should automatically process user speech and generate a response")
                            # RETURN immediately - don't process modelTurn (like reference)
                            continue
                        
                        # Check for turn_complete after interruption - this indicates the AI's turn is complete
                        # and Live API is ready to process user speech
                        # NOTE: After turn_complete, Live API waits for end-of-speech detection before processing user speech
                        if self._last_interruption_response > 0:
                            if response_count - self._last_interruption_response <= 5:
                                try:
                                    if hasattr(server_content, 'model_dump'):
                                        sc_dict = server_content.model_dump()
                                        if 'turn_complete' in sc_dict and sc_dict['turn_complete'] is True:
                                            self._turn_complete_response = response_count
                                            print(f"[LiveAPI] ✅ turn_complete = True after interruption (Response #{response_count})")
                                            print(f"[LiveAPI] ⏳ Live API is now waiting for user speech to complete (end-of-speech detection)")
                                            print(f"[LiveAPI] ⏳ User must pause for {50}ms for Live API to detect end-of-speech and process speech")
                                            print(f"[LiveAPI] ⚠️ CRITICAL: Live API requires {50}ms of silence to detect end-of-speech")
                                            print(f"[LiveAPI] ⚠️ If user speaks continuously, Live API will never detect end-of-speech and process speech")
                                except Exception as e:
                                    pass
                            
                            # CRITICAL: If turn_complete was detected but Live API continues sending model_turn responses
                            # for too long (15+ responses) without input_transcription, log timeout (but keep skipping)
                            # This prevents infinite loop where Live API is stuck generating responses
                            if self._turn_complete_response > 0:
                                responses_since_turn_complete = response_count - self._turn_complete_response
                                
                                # Log progress every 10 responses to track timeout progress (reduced noise)
                                if responses_since_turn_complete > 0 and responses_since_turn_complete % 10 == 0:
                                    print(f"[LiveAPI] ⏳ {responses_since_turn_complete} responses since turn_complete (still waiting for input_transcription)")
                                
                                if responses_since_turn_complete == 15:
                                    # First timeout - log warning once
                                    try:
                                        if hasattr(server_content, 'model_dump'):
                                            sc_dict = server_content.model_dump()
                                            if 'input_transcription' not in sc_dict or not sc_dict['input_transcription']:
                                                print(f"[LiveAPI] ⚠️⚠️⚠️ TIMEOUT: Live API sent 15+ model_turn responses after turn_complete without input_transcription ⚠️⚠️⚠️")
                                                print(f"[LiveAPI] ⚠️ Live API appears stuck - continuing to skip model_turn responses")
                                                # Clear the pause to allow audio sending to resume
                                                if self._pause_audio_until is not None:
                                                    self._pause_audio_until = None
                                                    print(f"[LiveAPI] ▶️ Resuming audio sending after timeout (but still skipping model_turn)")
                                            else:
                                                print(f"[LiveAPI] ✅ input_transcription appeared at response #{response_count}, resetting interruption state")
                                                self._last_interruption_response = 0
                                                self._turn_complete_response = 0
                                    except Exception as e:
                                        print(f"[LiveAPI] ⚠️ Error in timeout check: {e}")
                                        import traceback
                                        traceback.print_exc()
                                
                                # After 30 responses, reset interruption state to allow Live API to recover
                                if responses_since_turn_complete == 30:
                                    try:
                                        if hasattr(server_content, 'model_dump'):
                                            sc_dict = server_content.model_dump()
                                            if 'input_transcription' not in sc_dict or not sc_dict['input_transcription']:
                                                print(f"[LiveAPI] ⚠️⚠️⚠️ LONG TIMEOUT: Live API sent 30+ responses without input_transcription ⚠️⚠️⚠️")
                                                print(f"[LiveAPI] 🔄 Resetting interruption state to allow Live API to recover and process user speech")
                                                print(f"[LiveAPI] ⚠️ This allows normal processing to resume - Live API should process user speech now")
                                                self._last_interruption_response = 0
                                                self._turn_complete_response = 0
                                                # Clear pause if still active
                                                if self._pause_audio_until is not None:
                                                    self._pause_audio_until = None
                                                    print(f"[LiveAPI] ▶️ Resuming audio sending and normal processing")
                                    except Exception as e:
                                        print(f"[LiveAPI] ⚠️ Error in long timeout check: {e}")
                                        import traceback
                                        traceback.print_exc()
                        
                        # Check for user_turn (VAD detected user speech)
                        # This comes AFTER interruption and contains the user's speech transcription
                        # Live API will automatically respond to this user_turn
                        # Check both attribute and model_dump() since user_turn might be in dict but not as attribute
                        user_turn_detected = False
                        user_turn_content = None
                        
                        # Method 1: Check attribute
                        if hasattr(server_content, 'user_turn') and server_content.user_turn:
                            user_turn_detected = True
                            user_turn_content = server_content.user_turn
                        
                        # Method 2: Check model_dump() dictionary
                        if not user_turn_detected:
                            try:
                                if hasattr(server_content, 'model_dump'):
                                    sc_dict = server_content.model_dump()
                                    if 'user_turn' in sc_dict and sc_dict['user_turn']:
                                        user_turn_detected = True
                                        user_turn_content = sc_dict['user_turn']
                                        print(f"[LiveAPI] 🎤🎤🎤 USER_TURN FOUND IN model_dump()! Response #{response_count} 🎤🎤🎤")
                            except Exception as e:
                                if response_count <= 20 or (hasattr(self, '_last_interruption_response') and response_count - self._last_interruption_response <= 10):
                                    print(f"[LiveAPI] 🔍   Error checking user_turn in model_dump(): {e}")
                        
                        if user_turn_detected:
                            response_type = "user_turn"
                            print(f"[LiveAPI] 🎤🎤🎤 USER TURN DETECTED! Response #{response_count} 🎤🎤🎤")
                            # Log user transcript to see what Live API detected
                            if hasattr(user_turn_content, 'parts'):
                                for part in user_turn_content.parts:
                                    if hasattr(part, 'text') and part.text:
                                        print(f"[LiveAPI] 📝 User transcript: {part.text[:200]}...")
                            elif isinstance(user_turn_content, dict) and 'parts' in user_turn_content:
                                # Handle dict format
                                for part in user_turn_content['parts']:
                                    if isinstance(part, dict) and 'text' in part:
                                        print(f"[LiveAPI] 📝 User transcript (dict): {part['text'][:200]}...")
                            # Trigger interrupt callback to stop any remaining playback
                            cleared_count = 0
                            while not self.audio_queue_output.empty():
                                try:
                                    self.audio_queue_output.get_nowait()
                                    cleared_count += 1
                                except asyncio.QueueEmpty:
                                    break
                            if cleared_count > 0:
                                print(f"[LiveAPI] 🛑 Cleared {cleared_count} pending AI audio chunks from queue")
                            if self.on_user_turn_callback:
                                await self.on_user_turn_callback()
                            # IMPORTANT: Don't continue here - let Live API process the user_turn
                            # Live API will automatically generate a response to the user's speech
                            # Continue processing to receive the model's response
                        elif hasattr(server_content, 'model_turn') and server_content.model_turn:
                            response_type = "model_turn"
                        else:
                            response_type = "other_server_content"
                            # Log what other server_content we're getting
                            if response_count <= 20:  # Log first 20 to see structure
                                if isinstance(server_content, dict):
                                    print(f"[LiveAPI] 🔍 server_content dict keys: {list(server_content.keys())}")
                                else:
                                    attrs = [attr for attr in dir(server_content) if not attr.startswith('_')]
                                    print(f"[LiveAPI] 🔍 server_content type={type(server_content)}, attrs: {attrs[:15]}")
                                    # Try to get value of common attributes
                                    for attr in ['interrupted', 'model_turn', 'user_turn', 'turn_complete']:
                                        if hasattr(server_content, attr):
                                            try:
                                                val = getattr(server_content, attr)
                                                print(f"[LiveAPI] 🔍   {attr} = {val}")
                                            except:
                                                pass
                    elif hasattr(response, 'realtime_input') and response.realtime_input:
                        response_type = "realtime_input"
                    elif hasattr(response, 'turn_detection') and response.turn_detection:
                        response_type = "turn_detection"
                        print(f"[LiveAPI] 🔄 Turn detection event: {response.turn_detection}")
                    else:
                        # Log all attributes to see what we're missing
                        if response_count <= 10:
                            attrs = [attr for attr in dir(response) if not attr.startswith('_')]
                            print(f"[LiveAPI] 🔍 Response #{response_count} attrs: {attrs[:15]}")
                    
                    if should_log_response or response_type in ["user_turn", "interrupted"]:
                        log_msg = f"[LiveAPI] 📥 Response #{response_count}: type={response_type}"
                        if response_details:
                            log_msg += f", {', '.join(response_details)}"
                        print(log_msg)
                    
                    # Handle audio output - ONLY process modelTurn if NOT interrupted
                    # Reference pattern: Check interrupted FIRST, return if found, THEN process modelTurn
                    # We already checked interrupted above and continued if found, so this section only runs if NOT interrupted
                    if hasattr(response, 'server_content') and response.server_content:
                        server_content = response.server_content
                        
                        # DEBUG: After interruption, check if input_transcription appears (user speech detected)
                        if self._last_interruption_response > 0:
                            if response_count - self._last_interruption_response <= 30:
                                # Check for input_transcription in model_dump()
                                try:
                                    if hasattr(server_content, 'model_dump'):
                                        sc_dict = server_content.model_dump()
                                        if 'input_transcription' in sc_dict:
                                            input_trans = sc_dict['input_transcription']
                                            if input_trans:
                                                print(f"[LiveAPI] 🎤🎤🎤 INPUT_TRANSCRIPTION DETECTED AFTER INTERRUPTION! Response #{response_count} 🎤🎤🎤")
                                                print(f"[LiveAPI] 📝 User speech: {str(input_trans)[:200]}...")
                                                # Reset interruption tracking - Live API has processed user speech
                                                self._last_interruption_response = 0
                                                self._turn_complete_response = 0
                                                print(f"[LiveAPI] 🔄 Reset interruption tracking - Live API has processed user speech")
                                                # Resume audio sending immediately since user speech was detected
                                                if self._pause_audio_until is not None:
                                                    self._pause_audio_until = None
                                                    print(f"[LiveAPI] ▶️ Resuming audio sending - user speech detected and processed")
                                            else:
                                                if response_count - self._last_interruption_response <= 10:
                                                    print(f"[LiveAPI] ⏳ Waiting for input_transcription (user speech not yet detected)...")
                                except Exception as e:
                                    pass
                        
                        # CRITICAL: After interruption, skip processing ALL model_turn responses until we see input_transcription
                        # This prevents AI audio from playing when Live API should be processing user speech
                        # IMPORTANT: Continue skipping even after timeout - only stop when input_transcription appears
                        skip_model_turn_after_interruption = False
                        if self._last_interruption_response > 0:
                            # Continue checking indefinitely (not just for 30 responses) until input_transcription appears
                            # Check if input_transcription has appeared yet
                            try:
                                if hasattr(server_content, 'model_dump'):
                                    sc_dict = server_content.model_dump()
                                    if 'input_transcription' in sc_dict and sc_dict['input_transcription']:
                                        # User speech detected - allow model_turn processing and reset interruption state
                                        skip_model_turn_after_interruption = False
                                        self._last_interruption_response = 0
                                        self._turn_complete_response = 0
                                        print(f"[LiveAPI] ✅ input_transcription detected - resuming normal processing")
                                    else:
                                        # Still waiting for user speech - skip ALL model_turn processing
                                        skip_model_turn_after_interruption = True
                            except Exception as e:
                                skip_model_turn_after_interruption = True
                        
                        # CRITICAL: If we're waiting for user speech after interruption, skip processing model_turn entirely
                        if skip_model_turn_after_interruption and hasattr(response.server_content, 'model_turn') and response.server_content.model_turn:
                            # Skip this response entirely - don't process it at all
                            responses_since_interruption = response_count - self._last_interruption_response
                            if responses_since_interruption <= 5 or responses_since_interruption % 10 == 0:
                                print(f"[LiveAPI] ⏸️ Skipping model_turn response entirely after interruption (response #{responses_since_interruption} since interruption, waiting for input_transcription)...")
                            continue  # Skip processing this response entirely
                        
                        # Process modelTurn audio (only if we didn't already handle interrupted/user_turn above)
                        # Note: If interrupted was detected above, we already continued, so this won't run
                        if hasattr(response.server_content, 'model_turn') and response.server_content.model_turn:
                            if not skip_model_turn_after_interruption:
                                # Only process model_turn audio if we're not waiting for user speech after interruption
                                if hasattr(response.server_content.model_turn, 'parts'):
                                    for part in response.server_content.model_turn.parts:
                                        # Check for inline_data (audio)
                                        if hasattr(part, 'inline_data') and part.inline_data:
                                            if hasattr(part.inline_data, 'data') and isinstance(part.inline_data.data, bytes):
                                                audio_data = part.inline_data.data
                                                if len(audio_data) > 0:
                                                    audio_chunk_count += 1
                                                    if audio_chunk_count <= 20 or audio_chunk_count % 10 == 0:
                                                        print(f"[LiveAPI] 🔊 Received AI audio chunk #{audio_chunk_count}: {len(audio_data)} bytes")
                                                    if self.on_audio_callback:
                                                        await self.on_audio_callback(audio_data)
                                                    await self.audio_queue_output.put(audio_data)
                                        
                                        # Handle text output (for transcript)
                                        if hasattr(part, 'text') and part.text:
                                            text_chunk_count += 1
                                            print(f"[LiveAPI] 📝 Received text chunk #{text_chunk_count}: {part.text[:100]}...")
                                            if self.on_text_callback:
                                                await self.on_text_callback(part.text)
                    
                    # DEBUG: Log user_turn events (this comes AFTER interruption, contains user speech)
                    # NOTE: user_turn interrupt logic is now handled earlier (around line 170)
                    # This section is just for logging user transcript
                    if hasattr(response, 'server_content') and response.server_content:
                        if hasattr(response.server_content, 'user_turn') and response.server_content.user_turn:
                            print(f"[LiveAPI] 🎤 USER_TURN content received (user speech transcript)")
                            
                            if hasattr(response.server_content.user_turn, 'parts'):
                                for part in response.server_content.user_turn.parts:
                                    if hasattr(part, 'text') and part.text:
                                        print(f"[LiveAPI] 📝 User transcript: {part.text[:100]}...")
                                    # Also check for audio in user turn
                                    if hasattr(part, 'inline_data') and part.inline_data:
                                        print(f"[LiveAPI] 🎵 User turn contains audio data")
                    
                    # Also check for realtime_input events which might indicate user activity
                    if hasattr(response, 'realtime_input') and response.realtime_input:
                        print(f"[LiveAPI] 📡 Realtime input event received")
                        # Check if it's a user activity signal
                        if hasattr(response.realtime_input, 'user_activity_signal'):
                            print(f"[LiveAPI] 👤 User activity signal detected!")
                    
                    # Log periodically
                    if response_count % 50 == 0:
                        print(f"[LiveAPI] 📊 Processed {response_count} responses, {audio_chunk_count} audio chunks, {text_chunk_count} text chunks")
        except Exception as e:
            print(f"[LiveAPI] ✗ Error receiving from Live API: {e}")
            import traceback
            traceback.print_exc()
    
    async def send_audio(self, audio_data: bytes, interrupt: bool = False):
        """Send audio chunk to Live API.
        
        Args:
            audio_data: The audio bytes to send (PCM format)
            interrupt: If True, interrupt current turn before sending audio
        """
        # DEBUG: Track queued chunks
        if not hasattr(self, '_queued_log_count'):
            self._queued_log_count = 0
        self._queued_log_count += 1
        should_log = self._queued_log_count <= 20 or self._queued_log_count % 10 == 0
        
        if should_log:
            print(f"[LiveAPI] 📥 send_audio() called: {len(audio_data)} bytes PCM, interrupt={interrupt}")
        
        # Always clear output queue first if interrupting
        if interrupt:
            cleared_count = 0
            while not self.audio_queue_output.empty():
                try:
                    self.audio_queue_output.get_nowait()
                    cleared_count += 1
                except asyncio.QueueEmpty:
                    break
            if cleared_count > 0:
                print(f"[LiveAPI] 🛑 Interrupting AI - cleared {cleared_count} pending AI audio chunks from queue")
            else:
                print(f"[LiveAPI] 🛑 Interrupting AI - no pending audio to clear")
        
        # Always send user audio, even if interrupting
        # Skip empty audio chunks
        if len(audio_data) == 0:
            print(f"[LiveAPI] ⚠️ Skipping empty audio chunk")
            return
        
        await self.audio_queue_input.put(audio_data)
        
        if should_log:
            print(f"[LiveAPI] ✅ Queued user audio chunk #{self._queued_log_count}: {len(audio_data)} bytes PCM (interrupt={interrupt})")
    
    async def interrupt(self):
        """Interrupt the current response."""
        if self.live_session:
            # Clear output queue to stop playback
            cleared_count = 0
            while not self.audio_queue_output.empty():
                try:
                    self.audio_queue_output.get_nowait()
                    cleared_count += 1
                except asyncio.QueueEmpty:
                    break
            if cleared_count > 0:
                print(f"[LiveAPI] Interrupted - cleared {cleared_count} audio chunks")
            # Note: Sending user audio will automatically interrupt the AI
    
    async def stop(self):
        """Stop the Live API session."""
        self.is_running = False
        if self._context_manager:
            # Exit the async context manager properly
            await self._context_manager.__aexit__(None, None, None)
        self.live_session = None
        self._context_manager = None

