"""Test script to verify Live API interruption detection."""
import asyncio
import os
from dotenv import load_dotenv
from app.live_api import LiveAPISession

# Load environment variables
load_dotenv()


async def test_interruptions():
    """Test Live API interruption detection."""
    print("=" * 80)
    print("🧪 Testing Live API Interruption Detection")
    print("=" * 80)
    
    # Create a test session
    session_id = "test-interruptions-001"
    presentation_content = """
    This is a test presentation about AI and Machine Learning.
    
    Slide 1: Introduction
    - AI is transforming industries
    - Machine learning enables computers to learn from data
    
    Slide 2: Applications
    - Natural language processing
    - Computer vision
    - Recommendation systems
    """
    
    print(f"\n📋 Creating Live API session: {session_id}")
    live_session = LiveAPISession(session_id, presentation_content)
    
    # Set up callbacks
    audio_chunks_received = []
    text_chunks_received = []
    interruptions_detected = []
    
    async def on_audio_received(audio_data: bytes):
        audio_chunks_received.append(len(audio_data))
        if len(audio_chunks_received) <= 5:
            print(f"[Test] 🔊 Received audio chunk #{len(audio_chunks_received)}: {len(audio_data)} bytes")
    
    async def on_text_received(text: str):
        text_chunks_received.append(text)
        print(f"[Test] 📝 Received text: {text[:100]}...")
    
    async def on_user_turn_detected():
        interruptions_detected.append(True)
        print(f"[Test] 🛑🛑🛑 USER TURN DETECTED! Interruption #{len(interruptions_detected)} 🛑🛑🛑")
    
    live_session.on_audio_callback = on_audio_received
    live_session.on_text_callback = on_text_received
    live_session.on_user_turn_callback = on_user_turn_detected
    
    # Start the session
    print("\n🚀 Starting Live API session...")
    try:
        await live_session.start()
        print("✅ Session started successfully")
    except Exception as e:
        print(f"❌ Failed to start session: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Send initial prompt
    print("\n📤 Sending initial prompt...")
    try:
        prompt = "Hello! Please introduce this presentation about AI and Machine Learning. Start speaking now."
        await live_session.live_session.send_realtime_input(text=prompt)
        print("✅ Initial prompt sent")
    except Exception as e:
        print(f"❌ Failed to send prompt: {e}")
        import traceback
        traceback.print_exc()
    
    # Wait for some responses and monitor
    print("\n⏳ Monitoring Live API responses (15 seconds)...")
    print("   💡 TIP: Speak into your microphone during this time to test interruptions")
    print("   📊 Watching for:")
    print("      - Audio chunks from AI")
    print("      - Text transcripts")
    print("      - Interruption flags")
    print("      - User turn detection")
    print()
    
    # Monitor for a bit longer to see responses
    for i in range(15):
        await asyncio.sleep(1)
        if (i + 1) % 5 == 0:
            print(f"   ⏱️  {i+1}/15 seconds elapsed...")
    
    # Check results
    print("\n" + "=" * 80)
    print("📊 Test Results")
    print("=" * 80)
    print(f"✅ Audio chunks received: {len(audio_chunks_received)}")
    print(f"✅ Text chunks received: {len(text_chunks_received)}")
    print(f"🛑 Interruptions detected: {len(interruptions_detected)}")
    
    if interruptions_detected:
        print("\n✅ SUCCESS: Interruptions are being detected!")
    else:
        print("\n⚠️  WARNING: No interruptions detected")
        print("   This could mean:")
        print("   - Live API VAD is not detecting your speech")
        print("   - The interrupted flag is not being sent")
        print("   - Our detection logic needs adjustment")
        print("\n   Check the logs above for detailed response structure")
    
    # Cleanup
    print("\n🧹 Cleaning up...")
    await live_session.stop()
    print("✅ Test complete")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🔧 Live API Interruption Test")
    print("=" * 80)
    print("\nThis test will:")
    print("1. Create a Live API session")
    print("2. Send an initial prompt")
    print("3. Monitor for interruptions")
    print("4. Report results")
    print("\n💡 TIP: Speak into your microphone during the test to trigger interruptions")
    print("=" * 80 + "\n")
    
    asyncio.run(test_interruptions())

