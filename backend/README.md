# Voice Presentation Agent - Backend

FastAPI backend for the voice-powered presentation agent using Google Gemini Live API.

## Setup

1. Install dependencies using `uv`:
```bash
uv sync
```

2. Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```

3. Add your Gemini API key to `.env`:
```
GEMINI_API_KEY=your_api_key_here
```

## Running

Start the development server:
```bash
uv run fastapi dev
```

Or using uvicorn directly:
```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

## API Endpoints

- `GET /` - Health check
- `GET /health` - Health check
- `WebSocket /ws/live` - Live presentation WebSocket endpoint

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── models.py             # Data models (Slide, Session)
│   ├── schemas.py            # Pydantic schemas for WS messages
│   ├── session.py            # SlideManager, MemoryManager
│   ├── storage.py             # JSON file storage
│   ├── adk_tools.py          # ADK tool definitions
│   ├── adk_agent.py          # ADK agent configuration
│   ├── slide_generator.py    # Slide generation logic
│   └── websocket.py          # WebSocket endpoint & handlers
├── data/
│   ├── sessions/             # Session JSON files
│   └── memory/               # Memory JSON files
├── pyproject.toml
├── uv.lock
└── README.md
```

## Testing

Run automated conversation tests:

```bash
# Run all tests
uv run python backend/test_conversation.py

# Or with custom WebSocket URL
uv run python backend/test_conversation.py ws://localhost:8000/ws/live
```

See `TESTING.md` for detailed test documentation.

## WebSocket Protocol

See `app/schemas.py` for message type definitions.

### Client Messages
- `CLIENT_CONFIG` - Initialize session with topic
- `CLIENT_AUDIO` - Send audio chunks
- `CLIENT_INTERRUPT` - Interrupt current response
- `CLIENT_CONTROL` - Manual slide navigation
- `CLIENT_TEXT` - Text input (for testing)

### Server Messages
- `SERVER_READY` - Session initialized
- `SERVER_TRANSCRIPT` - User/assistant transcript
- `SERVER_AUDIO` - Audio stream chunks
- `SERVER_INTERRUPT` - Interruption detected
- `SERVER_SLIDE_EVENT` - Slide navigation events
- `SERVER_STATE` - Current slide state
- `SERVER_END` - Session ended
- `SERVER_ERROR` - Error message




