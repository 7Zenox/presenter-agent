"""Basic voice conversational server using OpenAI Realtime API."""
import asyncio
import os
import queue
import threading
from agents.realtime import RealtimeAgent, RealtimeRunner
from dotenv import load_dotenv

try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

load_dotenv()

# Audio configuration
SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK_SIZE = 2400  # 100ms chunks for lower latency
DTYPE = np.int16


class ConversationServer:
    """Basic conversational server."""
    
    def __init__(self):
        self.runner = None
        self.session = None
        self.is_running = False
        self.event_loop = None
        self.audio_queue = queue.Queue()
        self.audio_buffer = bytearray()
        self.buffer_lock = threading.Lock()
        self.output_stream = None
    
    async def start(self):
        """Start the server."""
        if not AUDIO_AVAILABLE:
            raise RuntimeError("Audio libraries not available")
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        
        # Create agent
        agent = RealtimeAgent(
            name="Assistant",
            instructions="You are a helpful assistant. Speak naturally.",
        )
        
        # Create runner
        self.runner = RealtimeRunner(
            starting_agent=agent,
            config={
                "model_settings": {
                    "model_name": "gpt-realtime",
                    "voice": "alloy",
                    "modalities": ["audio"],
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {
                        "type": "semantic_vad",
                        "eagerness": "medium",
                        "create_response": True,
                        "interrupt_response": True,
                    },
                }
            },
        )
        
        # Get event loop
        self.event_loop = asyncio.get_running_loop()
        
        # Start session
        self.session = await self.runner.run()
        self.is_running = True
        
        # Start audio output stream (for smooth playback)
        self._start_audio_output()
        
        # Start audio capture
        asyncio.create_task(self._capture_audio())
        
        # Start event loop
        await self._receive_events()
    
    def _audio_callback(self, indata, frames, time, status):
        """Audio input callback."""
        # Convert to bytes
        audio_bytes = indata.astype(DTYPE).tobytes()
        
        # Send to session
        if self.session and self.event_loop and not self.event_loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    self.session.send_audio(audio_bytes),
                    self.event_loop
                )
            except Exception as e:
                pass  # Silently handle audio send errors
    
    async def _capture_audio(self):
        """Capture audio from microphone."""
        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=CHUNK_SIZE,
                callback=self._audio_callback,
            ):
                while self.is_running:
                    await asyncio.sleep(1)
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    def _audio_output_callback(self, outdata, frames, time, status):
        """Callback for audio output stream - provides smooth playback."""
        with self.buffer_lock:
            bytes_needed = frames * CHANNELS * 2  # 2 bytes per sample (int16)
            
            # Fill buffer from queue if needed
            while len(self.audio_buffer) < bytes_needed:
                try:
                    chunk = self.audio_queue.get_nowait()
                    self.audio_buffer.extend(chunk)
                except queue.Empty:
                    break
            
            # Extract audio data
            if len(self.audio_buffer) >= bytes_needed:
                audio_data = bytes(self.audio_buffer[:bytes_needed])
                self.audio_buffer = self.audio_buffer[bytes_needed:]
                
                # Convert to numpy array
                audio_array = np.frombuffer(audio_data, dtype=DTYPE)
                audio_array = audio_array.reshape(-1, CHANNELS)
                outdata[:] = audio_array
            else:
                # Underflow - pad with zeros
                available = len(self.audio_buffer)
                if available > 0:
                    audio_data = bytes(self.audio_buffer)
                    self.audio_buffer.clear()
                    audio_array = np.frombuffer(audio_data, dtype=DTYPE)
                    audio_array = audio_array.reshape(-1, CHANNELS)
                    padding = np.zeros((frames - len(audio_array), CHANNELS), dtype=DTYPE)
                    audio_array = np.concatenate([audio_array, padding])
                    outdata[:] = audio_array
                else:
                    outdata.fill(0)
    
    def _start_audio_output(self):
        """Start audio output stream for smooth playback."""
        try:
            self.output_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=CHUNK_SIZE // 2,  # Smaller blocksize for smoother playback
                callback=self._audio_output_callback,
                latency='low',  # Low latency mode
            )
            self.output_stream.start()
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    async def _receive_events(self):
        """Receive and handle events from OpenAI."""
        try:
            async with self.session:
                async for event in self.session:
                    if not self.is_running:
                        break
                    
                    # Get event type for proper handling
                    event_type = getattr(event, "type", None)
                    
                    # Handle interruptions - clear audio buffer immediately
                    # According to docs: audio_interrupted and response.interrupted events
                    if (event_type == "response.interrupted" or 
                        event_type == "audio_interrupted" or
                        (hasattr(event, "interrupted") and event.interrupted)):
                        # Clear audio queue and buffer immediately
                        while not self.audio_queue.empty():
                            try:
                                self.audio_queue.get_nowait()
                            except queue.Empty:
                                break
                        with self.buffer_lock:
                            self.audio_buffer.clear()
                        # Also stop any currently playing audio
                        try:
                            sd.stop()
                        except:
                            pass
                    
                    # Handle audio output - queue for smooth playback
                    elif hasattr(event, "audio") and event.audio:
                        audio_data = event.audio
                        if isinstance(audio_data, bytes):
                            try:
                                self.audio_queue.put_nowait(audio_data)
                            except queue.Full:
                                # Drop oldest chunk if queue is full
                                try:
                                    self.audio_queue.get_nowait()
                                    self.audio_queue.put_nowait(audio_data)
                                except queue.Empty:
                                    pass
                        elif hasattr(audio_data, "data"):
                            try:
                                self.audio_queue.put_nowait(audio_data.data)
                            except queue.Full:
                                try:
                                    self.audio_queue.get_nowait()
                                    self.audio_queue.put_nowait(audio_data.data)
                                except queue.Empty:
                                    pass
                    
                    # Handle response completion
                    elif event_type == "response.done":
                        pass
                    
                    # Handle response start
                    elif event_type == "response.created":
                        pass
                    
                    # Handle transcripts
                    elif hasattr(event, "text") and event.text:
                        pass
                    
                    # Handle user transcripts
                    elif hasattr(event, "input_audio_transcription"):
                        transcript = getattr(event.input_audio_transcription, "transcript", None)
                        if transcript:
                            pass
        
        except Exception as e:
            import traceback
            traceback.print_exc()
    
    async def stop(self):
        """Stop the server."""
        self.is_running = False
        
        # Stop audio output stream
        if self.output_stream:
            try:
                self.output_stream.stop()
                self.output_stream.close()
            except:
                pass
        
        if self.session:
            try:
                await self.session.close()
            except:
                pass


async def main():
    """Main function."""
    if not AUDIO_AVAILABLE:
        return
    
    server = ConversationServer()
    
    try:
        await server.start()
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())