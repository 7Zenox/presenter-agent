# Automated Conversation Testing

This document describes how to use the automated test script to test conversation flows and interruption handling.

## Prerequisites

1. Backend server must be running on `http://localhost:8000`
2. All dependencies installed (including `websockets`)

## Running Tests

### Basic Usage

```bash
# Run all tests with default WebSocket URL (ws://localhost:8000/ws/live)
python backend/test_conversation.py

# Or specify a custom WebSocket URL
python backend/test_conversation.py ws://localhost:8000/ws/live
```

### Using uv

```bash
# From project root
uv run python backend/test_conversation.py
```

## Test Cases

The script runs the following test cases:

### 1. Basic Conversation Flow
- **Purpose**: Verify basic conversation works
- **Steps**:
  1. Connect to WebSocket
  2. Send CLIENT_CONFIG
  3. Send audio chunks (simulating user speech)
  4. Wait for AI response
- **Expected**: AI responds with SERVER_AUDIO or SERVER_TRANSCRIPT

### 2. Interruption Handling
- **Purpose**: Test interruption detection and response
- **Steps**:
  1. Start conversation
  2. Trigger AI response
  3. Send CLIENT_INTERRUPT
  4. Send user speech after interruption
  5. Wait for AI response
- **Expected**: 
  - SERVER_INTERRUPT received
  - User transcript received
  - AI responds to user speech

### 3. Interruption with Pause (End-of-Speech)
- **Purpose**: Test interruption with pause for end-of-speech detection
- **Steps**:
  1. Start conversation
  2. Trigger AI response
  3. Send CLIENT_INTERRUPT
  4. Send user speech
  5. **Pause 200ms** (critical for end-of-speech detection)
  6. Send silence chunks
  7. Wait for AI response
- **Expected**: AI responds after pause

### 4. Continuous Speech (No Pause)
- **Purpose**: Test behavior with continuous speech (no end-of-speech)
- **Steps**:
  1. Start conversation
  2. Send CLIENT_INTERRUPT
  3. Send continuous audio chunks without pause
  4. Wait for AI response
- **Expected**: May fail (expected - Live API needs end-of-speech)

## Understanding Results

### Test Result Types

- **✅ PASS**: Test passed - expected behavior occurred
- **❌ FAIL**: Test failed - expected behavior did not occur
- **⏱️ TIMEOUT**: Test timed out - no response within timeout period

### Common Issues

1. **"SERVER_READY timeout"**
   - Backend server not running
   - WebSocket URL incorrect
   - Backend not responding

2. **"No AI response received"**
   - Live API not configured correctly
   - API key missing or invalid
   - Network issues

3. **"User transcript not received after interruption"**
   - Interruption not detected
   - Live API not processing user speech
   - End-of-speech not detected

4. **"AI did not respond after pause"**
   - Live API stuck in broken state
   - End-of-speech detection not working
   - May need to restart Live API session

## Debugging

### Enable Verbose Logging

The test script logs all important events:
- WebSocket connection/disconnection
- Messages sent/received
- Test results

### Check Backend Logs

While running tests, monitor backend logs for:
- Interruption detection: `🛑🛑🛑 INTERRUPTED KEY FOUND`
- Turn complete: `✅ turn_complete = True after interruption`
- Input transcription: `🎤🎤🎤 INPUT_TRANSCRIPTION DETECTED`
- Audio pause/resume: `⏸️ Pausing audio sending` / `▶️ Resuming audio sending`

### Manual Testing

For manual testing, you can modify the test script to:
- Add delays between steps
- Change audio generation parameters
- Test specific scenarios
- Add more detailed logging

## Example Output

```
============================================================
[Test] Starting Automated Conversation Tests
============================================================
[Test] 🔌 Connecting to ws://localhost:8000/ws/live...
[Test] ✅ Connected

============================================================
[Test] Test 1: Basic Conversation Flow
============================================================
[Test] 📤 Sent CLIENT_CONFIG: topic=Test Topic
[Test] ✅ Received SERVER_READY: sessionId=abc-123
[Test] 📤 Sent CLIENT_AUDIO chunk #0: 4096 bytes
...
✅ basic_conversation: PASS
   Message: Received AI response

============================================================
[Test] Test 2: Interruption Handling
============================================================
...
✅ interruption: PASS
   Message: Interruption handled correctly

============================================================
[Test] Test Summary
============================================================
Total: 4
✅ Passed: 3
❌ Failed: 1
⏱️ Timeout: 0
```

## Extending Tests

To add new test cases, create a new async method in the `ConversationTester` class:

```python
async def test_my_scenario(self) -> Dict:
    """Test description."""
    print("\n" + "="*60)
    print("[Test] Test Name")
    print("="*60)
    
    self.received_messages.clear()
    self.received_events.clear()
    
    # Your test steps here
    await self.send_config("Topic")
    await self.wait_for_event("SERVER_READY", timeout=10.0)
    
    # ... more steps ...
    
    # Return result
    return {
        "test": "my_scenario",
        "result": TestResult.PASS,  # or FAIL or TIMEOUT
        "message": "Description of result"
    }
```

Then add it to the `run_all_tests()` method's `tests` list.

