"""FastAPI application entry point."""
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.websocket import websocket_endpoint

# Load environment variables
load_dotenv()

app = FastAPI(title="Voice Presentation Agent API")

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include WebSocket route
app.websocket("/ws/live")(websocket_endpoint)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Voice Presentation Agent API"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

