"""Data models for the presentation agent."""
from dataclasses import dataclass, field
from typing import List
from datetime import datetime


@dataclass
class Slide:
    """Represents a single slide in the presentation."""
    id: int
    title: str
    bullets: List[str] = field(default_factory=list)


@dataclass
class Session:
    """Represents a presentation session."""
    session_id: str
    topic: str
    slides: List[Slide] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)




