# Presenter Agent

An AI-powered voice-controlled presentation system that uses OpenAI's Realtime API to navigate and present PowerPoint slides through natural conversation.

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- OpenAI API Key (set in `.env` file)

### Installation

```bash
# Install all dependencies
make install

# Or install separately
make install-backend
make install-frontend
```

### Running the Servers

```bash
# Run both backend and frontend together
make dev-all

# Or run separately
make dev-backend    # Backend on http://localhost:8000
make dev-frontend   # Frontend on http://localhost:5173
```

## 📋 Project Overview

Presenter Agent is a voice-controlled AI assistant that helps you navigate and present PowerPoint presentations using natural language. Simply speak commands like "next slide", "go to slide 5", or ask questions about the content, and the AI will navigate and present accordingly.

### Key Features

- 🎤 **Voice-controlled navigation** - Navigate slides using natural voice commands
- 🔍 **Semantic search** - Find content by asking questions
- 💬 **Natural conversation** - Interactive Q&A during presentations
- 📊 **Smart content handling** - Efficiently handles both small and large presentations
- 🔄 **Real-time synchronization** - Slide display syncs with AI responses
- 🌐 **Web-based interface** - Cross-platform web application

## 🏗️ Architecture

- **Frontend**: React + TypeScript + Web Audio API
- **Backend**: FastAPI (Python) with WebSocket support
- **AI**: OpenAI Realtime API (gpt-realtime model)
- **Communication**: WebSocket for real-time bidirectional messaging

## 📁 Project Structure

```
presenter-agent/
├── backend/          # FastAPI backend server
│   └── app/
│       ├── main.py              # Main WebSocket server
│       ├── presentation.py      # PPTX parser and slide manager
│       └── conversation_server.py
├── frontend/         # React frontend application
│   └── src/
│       ├── App.tsx
│       └── utils/
│           └── audio-manager.ts  # WebSocket & audio handling
└── Makefile          # Convenient commands for development
```

## 🔧 Configuration

Create a `.env` file in the `backend/` directory:

```env
OPENAI_API_KEY=your_api_key_here
```

## 📝 Available Commands

```bash
make help              # Show all available commands
make install           # Install all dependencies
make dev-all           # Run both servers
make build             # Build frontend for production
make clean             # Clean build artifacts
```

## 🎯 Usage

1. Upload a PowerPoint (.pptx) file through the web interface
2. Click "Start Presentation" to begin
3. Speak naturally:
   - "Next slide"
   - "Go to slide 5"
   - "What does slide 3 say about X?"
   - "Search for information about Y"

The AI will navigate slides, present content naturally, and answer questions about your presentation.

## 🛠️ Development

### Backend Development

```bash
cd backend
fastapi dev app/main.py --host 0.0.0.0 --port 8000
```

### Frontend Development

```bash
cd frontend
npm run dev
```
