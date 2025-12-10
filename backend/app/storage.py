"""JSON file storage for sessions and memory."""
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
from app.models import Slide, Session
from app.session import SlideManager, MemoryManager


# Storage directories
BASE_DIR = Path(__file__).parent.parent
SESSIONS_DIR = BASE_DIR / "data" / "sessions"
MEMORY_DIR = BASE_DIR / "data" / "memory"

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def save_session(session_id: str, topic: str, slides: list[Slide]):
    """Save session data to JSON file."""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    data = {
        "session_id": session_id,
        "topic": topic,
        "slides": [
            {
                "id": slide.id,
                "title": slide.title,
                "bullets": slide.bullets
            }
            for slide in slides
        ]
    }
    with open(session_file, "w") as f:
        json.dump(data, f, indent=2)


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Load session data from JSON file."""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    if not session_file.exists():
        return None
    
    with open(session_file, "r") as f:
        data = json.load(f)
    
    return data


def save_memory(session_id: str, memory_manager: MemoryManager):
    """Save memory state to JSON file."""
    memory_file = MEMORY_DIR / f"{session_id}.json"
    data = {
        "summary": memory_manager.summary,
        "recent": memory_manager.recent
    }
    with open(memory_file, "w") as f:
        json.dump(data, f, indent=2)


def load_memory(session_id: str) -> Optional[MemoryManager]:
    """Load memory state from JSON file."""
    memory_file = MEMORY_DIR / f"{session_id}.json"
    if not memory_file.exists():
        return None
    
    with open(memory_file, "r") as f:
        data = json.load(f)
    
    manager = MemoryManager()
    manager.summary = data.get("summary", "")
    manager.recent = data.get("recent", [])
    return manager




