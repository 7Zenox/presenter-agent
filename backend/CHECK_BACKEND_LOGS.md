# What to Check in Backend Logs

When you speak, look for these messages in your **backend terminal**:

## Critical Messages to Find:

### 1. Response Structure (should appear frequently):
```
[LiveAPI] 🔍 Response #X server_content type: <type>
[LiveAPI] 🔍   to_dict() keys: [...]
```

### 2. Interruption Detection (if working):
```
[LiveAPI] 🛑🛑🛑 INTERRUPTED KEY FOUND IN to_dict()!
[LiveAPI] 🛑 Calling interrupt callback
[WebSocket] 🛑 User turn detected - sending interrupt signal to frontend
```

### 3. User Turn Detection (VAD working):
```
[LiveAPI] 🎤🎤🎤 USER TURN DETECTED! Response #X
[LiveAPI] 🛑 Triggering interrupt callback based on user_turn detection
```

### 4. What Keys Are Available:
Look for lines like:
```
[LiveAPI] 🔍   to_dict() keys: ['model_turn', 'turn_complete', ...]
```

## If You See:
- **No `interrupted` key** in the keys list → Live API isn't sending it
- **No `user_turn` detected** → VAD isn't detecting your speech
- **Keys exist but no interrupt triggered** → Our detection logic needs fixing

## Please Share:
1. Backend terminal output (especially when you're speaking)
2. Look for lines with `🔍`, `🛑`, `🎤` emojis
3. Copy the first 50-100 lines after you start speaking

