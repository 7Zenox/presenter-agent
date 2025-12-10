# Voice Presentation Agent

A voice-powered presentation agent that generates slides and presents them using AI, with real-time audio streaming and slide navigation.

## Architecture

- **Backend**: FastAPI with Google Gemini Live API integration
- **Frontend**: React + Vite with WebSocket client and audio capture/playback

## Features

- 🎤 Real-time voice interaction with AI presenter
- 📊 Automatic slide generation from topic
- 🎯 Slide navigation with jump-and-resume logic
- 💾 Session and memory management
- 🔄 Interruption handling
- 📝 Conversation transcript

## Quick Start

### Backend Setup

1. Navigate to backend directory:
```bash
cd backend
```

2. Install dependencies:
```bash
uv sync
```

3. Create `.env` file:
```bash
cp .env.example .env
# Add your GEMINI_API_KEY
```

4. Start the server:
```bash
uv run fastapi dev
```

### Frontend Setup

1. Navigate to frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Create `.env` file:
```bash
cp .env.example .env
```

4. Start the dev server:
```bash
npm run dev
```

## Usage

1. Open the frontend at `http://localhost:5173`
2. Enter a presentation topic (e.g., "Quantum Computing 101")
3. Click "Start Presentation"
4. The AI will generate slides and begin presenting
5. You can interrupt, ask questions, or manually navigate slides

## Project Structure

```
presenter-agent/
├── backend/          # FastAPI backend
│   ├── app/          # Application code
│   ├── data/         # Session and memory storage
│   └── pyproject.toml
├── frontend/         # React frontend
│   ├── src/          # Source code
│   └── package.json
└── README.md
```

## Development

### Backend
- Uses `uv` for dependency management
- FastAPI for WebSocket and API endpoints
- Google Generative AI SDK for Gemini integration

### Frontend
- React 18 with TypeScript
- Vite for build tooling
- WebSocket for real-time communication
- MediaRecorder API for audio capture

## License

MIT




