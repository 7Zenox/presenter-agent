#!/usr/bin/env python3
"""Automated test script for conversation and interruption handling."""
import asyncio
import json
import base64
import time
import websockets
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class TestResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"


@dataclass
class TestCase:
    name: str
    description: str
    expected_events: List[str]
    timeout: float = 30.0


class ConversationTester:
    """Automated tester for conversation flow."""
    
    def __init__(self, ws_url: str = "ws://localhost:8000/ws/live"):
        self.ws_url = ws_url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.session_id: Optional[str] = None
        self.received_messages: List[Dict] = []
        self.received_events: List[str] = []
        self.test_results: List[Dict] = []
        
    async def connect(self):
        """Connect to WebSocket."""
        print(f"[Test] 🔌 Connecting to {self.ws_url}...")
        self.ws = await websockets.connect(self.ws_url)
        print(f"[Test] ✅ Connected")
        
    async def disconnect(self):
        """Disconnect from WebSocket."""
        if self.ws:
            await self.ws.close()
            print(f"[Test] 🔌 Disconnected")
    
    async def send_config(self, topic: str = "Test Presentation"):
        """Send CLIENT_CONFIG to start session."""
        message = {
            "type": "CLIENT_CONFIG",
            "topic": topic
        }
        await self.ws.send(json.dumps(message))
        print(f"[Test] 📤 Sent CLIENT_CONFIG: topic={topic}")
    
    def generate_silence_audio(self, duration_ms: int = 128) -> bytes:
        """Generate silence audio chunk (PCM16, 16kHz)."""
        # 16kHz sample rate, 16-bit PCM
        num_samples = int(16000 * duration_ms / 1000)
        # Generate silence (zeros)
        audio_data = b'\x00\x00' * num_samples
        return audio_data
    
    def generate_tone_audio(self, frequency: int = 440, duration_ms: int = 128, sample_rate: int = 16000) -> bytes:
        """Generate a tone audio chunk (PCM16, 16kHz)."""
        import math
        num_samples = int(sample_rate * duration_ms / 1000)
        audio_data = bytearray()
        for i in range(num_samples):
            # Generate sine wave
            sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate))
            # Convert to 16-bit little-endian
            audio_data.extend(sample.to_bytes(2, byteorder='little', signed=True))
        return bytes(audio_data)
    
    async def send_audio_chunk(self, audio_data: bytes, chunk_num: int = 0):
        """Send audio chunk to server."""
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
        message = {
            "type": "CLIENT_AUDIO",
            "encoding": "linear16",
            "sampleRate": 16000,
            "data": audio_b64
        }
        await self.ws.send(json.dumps(message))
        if chunk_num <= 5 or chunk_num % 10 == 0:
            print(f"[Test] 📤 Sent CLIENT_AUDIO chunk #{chunk_num}: {len(audio_data)} bytes")
    
    async def send_interrupt(self):
        """Send interrupt signal."""
        message = {"type": "CLIENT_INTERRUPT"}
        await self.ws.send(json.dumps(message))
        print(f"[Test] 🛑 Sent CLIENT_INTERRUPT")
    
    async def receive_messages(self, timeout: float = 30.0):
        """Receive messages from WebSocket with timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Set a shorter timeout for each receive attempt
                message = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                data = json.loads(message)
                self.received_messages.append(data)
                msg_type = data.get("type", "UNKNOWN")
                self.received_events.append(msg_type)
                
                # Log important messages
                if msg_type == "SERVER_READY":
                    self.session_id = data.get("sessionId")
                    print(f"[Test] ✅ Received SERVER_READY: sessionId={self.session_id}")
                elif msg_type == "SERVER_INTERRUPT":
                    print(f"[Test] 🛑 Received SERVER_INTERRUPT")
                elif msg_type == "SERVER_TRANSCRIPT":
                    role = data.get("role", "unknown")
                    text = data.get("text", "")[:100]
                    print(f"[Test] 📝 Received SERVER_TRANSCRIPT: role={role}, text={text}...")
                elif msg_type == "SERVER_AUDIO":
                    seq = data.get("sequence", 0)
                    if seq <= 5 or seq % 10 == 0:
                        print(f"[Test] 🔊 Received SERVER_AUDIO: sequence={seq}")
                elif msg_type == "SERVER_ERROR":
                    print(f"[Test] ❌ Received SERVER_ERROR: {data.get('message', '')}")
                elif msg_type == "SERVER_END":
                    print(f"[Test] 🏁 Received SERVER_END: reason={data.get('reason', '')}")
                    break
            except asyncio.TimeoutError:
                # Continue waiting
                continue
            except websockets.exceptions.ConnectionClosed:
                print(f"[Test] ⚠️ Connection closed")
                break
    
    async def wait_for_event(self, event_type: str, timeout: float = 10.0) -> bool:
        """Wait for a specific event type."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if event_type in self.received_events:
                return True
            try:
                message = await asyncio.wait_for(self.ws.recv(), timeout=0.5)
                data = json.loads(message)
                msg_type = data.get("type", "UNKNOWN")
                self.received_messages.append(data)
                self.received_events.append(msg_type)
                if msg_type == event_type:
                    return True
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                return False
        return False
    
    def check_events(self, expected_events: List[str]) -> bool:
        """Check if expected events occurred (in order)."""
        event_idx = 0
        for received_event in self.received_events:
            if event_idx < len(expected_events) and received_event == expected_events[event_idx]:
                event_idx += 1
        return event_idx == len(expected_events)
    
    async def test_basic_conversation(self) -> Dict:
        """Test 1: Basic conversation flow."""
        print("\n" + "="*60)
        print("[Test] Test 1: Basic Conversation Flow")
        print("="*60)
        
        self.received_messages.clear()
        self.received_events.clear()
        
        # Start session
        await self.send_config("Test Topic")
        
        # Wait for SERVER_READY
        ready = await self.wait_for_event("SERVER_READY", timeout=10.0)
        if not ready:
            return {"test": "basic_conversation", "result": TestResult.TIMEOUT, "message": "SERVER_READY timeout"}
        
        # Send a few audio chunks (simulating user speech)
        for i in range(10):
            audio = self.generate_tone_audio(frequency=440, duration_ms=128)
            await self.send_audio_chunk(audio, chunk_num=i)
            await asyncio.sleep(0.1)  # 100ms between chunks
        
        # Wait for AI response (should get SERVER_AUDIO or SERVER_TRANSCRIPT)
        await asyncio.sleep(3.0)  # Give AI time to respond
        
        # Check if we got any response
        has_audio = "SERVER_AUDIO" in self.received_events
        has_transcript = "SERVER_TRANSCRIPT" in self.received_events
        
        if has_audio or has_transcript:
            return {"test": "basic_conversation", "result": TestResult.PASS, "message": "Received AI response"}
        else:
            return {"test": "basic_conversation", "result": TestResult.FAIL, "message": "No AI response received"}
    
    async def test_interruption(self) -> Dict:
        """Test 2: Interruption handling."""
        print("\n" + "="*60)
        print("[Test] Test 2: Interruption Handling")
        print("="*60)
        
        self.received_messages.clear()
        self.received_events.clear()
        
        # Start session
        await self.send_config("Test Topic")
        await self.wait_for_event("SERVER_READY", timeout=10.0)
        
        # Send audio to trigger AI response
        for i in range(5):
            audio = self.generate_tone_audio(frequency=440, duration_ms=128)
            await self.send_audio_chunk(audio, chunk_num=i)
            await asyncio.sleep(0.1)
        
        # Wait a bit for AI to start responding
        await asyncio.sleep(1.0)
        
        # Check if AI started responding
        initial_audio_count = sum(1 for e in self.received_events if e == "SERVER_AUDIO")
        
        # Send interrupt
        await self.send_interrupt()
        
        # Wait for SERVER_INTERRUPT confirmation
        interrupt_received = await self.wait_for_event("SERVER_INTERRUPT", timeout=5.0)
        
        # Send user speech after interruption
        await asyncio.sleep(0.5)  # Brief pause
        for i in range(10):
            audio = self.generate_tone_audio(frequency=550, duration_ms=128)
            await self.send_audio_chunk(audio, chunk_num=i)
            await asyncio.sleep(0.1)
        
        # Wait for AI to respond to user speech
        await asyncio.sleep(5.0)
        
        # Check results
        final_audio_count = sum(1 for e in self.received_events if e == "SERVER_AUDIO")
        has_interrupt = "SERVER_INTERRUPT" in self.received_events
        has_user_transcript = any(
            msg.get("type") == "SERVER_TRANSCRIPT" and msg.get("role") == "user"
            for msg in self.received_messages
        )
        has_assistant_response = any(
            msg.get("type") == "SERVER_TRANSCRIPT" and msg.get("role") == "assistant"
            for msg in self.received_messages[-10:]  # Check last 10 messages
        )
        
        result_msg = []
        if not has_interrupt:
            result_msg.append("SERVER_INTERRUPT not received")
        if not has_user_transcript:
            result_msg.append("User transcript not received after interruption")
        if not has_assistant_response:
            result_msg.append("Assistant response not received after interruption")
        
        if not result_msg:
            return {"test": "interruption", "result": TestResult.PASS, "message": "Interruption handled correctly"}
        else:
            return {"test": "interruption", "result": TestResult.FAIL, "message": "; ".join(result_msg)}
    
    async def test_interruption_with_pause(self) -> Dict:
        """Test 3: Interruption with pause (end-of-speech detection)."""
        print("\n" + "="*60)
        print("[Test] Test 3: Interruption with Pause (End-of-Speech)")
        print("="*60)
        
        self.received_messages.clear()
        self.received_events.clear()
        
        # Start session
        await self.send_config("Test Topic")
        await self.wait_for_event("SERVER_READY", timeout=10.0)
        
        # Send audio to trigger AI response
        for i in range(5):
            audio = self.generate_tone_audio(frequency=440, duration_ms=128)
            await self.send_audio_chunk(audio, chunk_num=i)
            await asyncio.sleep(0.1)
        
        # Wait for AI to start responding
        await asyncio.sleep(1.0)
        
        # Send interrupt
        await self.send_interrupt()
        await self.wait_for_event("SERVER_INTERRUPT", timeout=5.0)
        
        # Send user speech
        for i in range(5):
            audio = self.generate_tone_audio(frequency=550, duration_ms=128)
            await self.send_audio_chunk(audio, chunk_num=i)
            await asyncio.sleep(0.1)
        
        # CRITICAL: Pause for end-of-speech detection (50ms+)
        print(f"[Test] ⏸️ Pausing for 200ms to allow end-of-speech detection...")
        await asyncio.sleep(0.2)
        
        # Send silence chunks to help Live API detect end-of-speech
        for i in range(3):
            silence = self.generate_silence_audio(duration_ms=128)
            await self.send_audio_chunk(silence, chunk_num=i)
            await asyncio.sleep(0.1)
        
        # Wait for AI response
        await asyncio.sleep(5.0)
        
        # Check if AI responded
        has_assistant_response = any(
            msg.get("type") == "SERVER_TRANSCRIPT" and msg.get("role") == "assistant"
            for msg in self.received_messages[-10:]
        ) or "SERVER_AUDIO" in self.received_events[-10:]
        
        if has_assistant_response:
            return {"test": "interruption_with_pause", "result": TestResult.PASS, "message": "AI responded after pause"}
        else:
            return {"test": "interruption_with_pause", "result": TestResult.FAIL, "message": "AI did not respond after pause"}
    
    async def test_continuous_speech(self) -> Dict:
        """Test 4: Continuous speech without pause."""
        print("\n" + "="*60)
        print("[Test] Test 4: Continuous Speech (No Pause)")
        print("="*60)
        
        self.received_messages.clear()
        self.received_events.clear()
        
        # Start session
        await self.send_config("Test Topic")
        await self.wait_for_event("SERVER_READY", timeout=10.0)
        
        # Send interrupt
        await self.send_interrupt()
        await self.wait_for_event("SERVER_INTERRUPT", timeout=5.0)
        
        # Send continuous audio without pause
        for i in range(30):  # 30 chunks = ~3.8 seconds
            audio = self.generate_tone_audio(frequency=550, duration_ms=128)
            await self.send_audio_chunk(audio, chunk_num=i)
            await asyncio.sleep(0.128)  # Continuous, no gaps
        
        # Wait for AI response
        await asyncio.sleep(5.0)
        
        # Check if AI responded (might not due to no end-of-speech)
        has_assistant_response = any(
            msg.get("type") == "SERVER_TRANSCRIPT" and msg.get("role") == "assistant"
            for msg in self.received_messages[-10:]
        ) or "SERVER_AUDIO" in self.received_events[-10:]
        
        if has_assistant_response:
            return {"test": "continuous_speech", "result": TestResult.PASS, "message": "AI responded despite continuous speech"}
        else:
            return {"test": "continuous_speech", "result": TestResult.FAIL, "message": "AI did not respond (expected - no end-of-speech detected)"}
    
    async def run_all_tests(self):
        """Run all test cases."""
        print("\n" + "="*60)
        print("[Test] Starting Automated Conversation Tests")
        print("="*60)
        
        try:
            await self.connect()
            
            # Run tests
            tests = [
                self.test_basic_conversation(),
                self.test_interruption(),
                self.test_interruption_with_pause(),
                self.test_continuous_speech(),
            ]
            
            results = []
            for test_coro in tests:
                try:
                    result = await test_coro
                    results.append(result)
                    self.test_results.append(result)
                    
                    status = "✅" if result["result"] == TestResult.PASS else "❌" if result["result"] == TestResult.FAIL else "⏱️"
                    print(f"\n{status} {result['test']}: {result['result'].value}")
                    print(f"   Message: {result['message']}")
                    
                    # Small delay between tests
                    await asyncio.sleep(2.0)
                except Exception as e:
                    print(f"\n❌ Test failed with exception: {e}")
                    import traceback
                    traceback.print_exc()
                    results.append({
                        "test": "unknown",
                        "result": TestResult.FAIL,
                        "message": f"Exception: {str(e)}"
                    })
            
            # Print summary
            print("\n" + "="*60)
            print("[Test] Test Summary")
            print("="*60)
            passed = sum(1 for r in results if r["result"] == TestResult.PASS)
            failed = sum(1 for r in results if r["result"] == TestResult.FAIL)
            timeout = sum(1 for r in results if r["result"] == TestResult.TIMEOUT)
            total = len(results)
            
            print(f"Total: {total}")
            print(f"✅ Passed: {passed}")
            print(f"❌ Failed: {failed}")
            print(f"⏱️ Timeout: {timeout}")
            
            for result in results:
                status = "✅" if result["result"] == TestResult.PASS else "❌" if result["result"] == TestResult.FAIL else "⏱️"
                print(f"  {status} {result['test']}: {result['message']}")
            
        finally:
            await self.disconnect()


async def main():
    """Main entry point."""
    import sys
    
    ws_url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000/ws/live"
    
    tester = ConversationTester(ws_url=ws_url)
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())

