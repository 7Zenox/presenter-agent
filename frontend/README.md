# Voice Presentation Agent - Frontend

React + Vite frontend for the voice-powered presentation agent.

## Setup

1. Install dependencies:
```bash
npm install
```

2. Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```

3. Update `.env` with your backend WebSocket URL if needed:
```
VITE_WS_URL=ws://localhost:8000/ws/live
```

## Running

Start the development server:
```bash
npm run dev
```

The app will be available at `http://localhost:5173`

## Building

Build for production:
```bash
npm run build
```

The built files will be in the `dist/` directory.

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── Slide.tsx
│   │   ├── SlideContainer.tsx
│   │   └── ControlPanel.tsx
│   ├── hooks/
│   │   ├── useLiveSession.ts
│   │   ├── useAudioCapture.ts
│   │   └── useAudioPlayback.ts
│   ├── types/
│   │   ├── messages.ts
│   │   └── slide.ts
│   ├── App.tsx
│   └── main.tsx
├── package.json
└── vite.config.ts
```

## Features

- Real-time WebSocket communication with backend
- Audio capture using MediaRecorder API
- Audio playback for AI responses
- Slide navigation and display
- Presentation controls (start/stop, interrupt, manual navigation)
