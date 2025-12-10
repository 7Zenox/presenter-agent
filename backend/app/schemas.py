"""Pydantic schemas for WebSocket messages."""
from pydantic import BaseModel
from typing import Optional, Literal


# Client → Server messages

class ClientConfig(BaseModel):
    """Client configuration message."""
    type: Literal["CLIENT_CONFIG"] = "CLIENT_CONFIG"
    topic: Optional[str] = None  # Optional, for display purposes
    voice: Optional[str] = None
    lang: Optional[str] = "en-US"


class ClientUploadPPT(BaseModel):
    """Client PowerPoint file upload message."""
    type: Literal["CLIENT_UPLOAD_PPT"] = "CLIENT_UPLOAD_PPT"
    filename: str
    data: str  # base64 encoded PowerPoint file data
    topic: Optional[str] = None  # Optional topic/name for the presentation


class ClientAudio(BaseModel):
    """Client audio chunk message."""
    type: Literal["CLIENT_AUDIO"] = "CLIENT_AUDIO"
    encoding: str = "linear16"
    sampleRate: int = 16000
    data: str  # base64 encoded audio


class ClientInterrupt(BaseModel):
    """Client interrupt message."""
    type: Literal["CLIENT_INTERRUPT"] = "CLIENT_INTERRUPT"


class ClientControl(BaseModel):
    """Client control message."""
    type: Literal["CLIENT_CONTROL"] = "CLIENT_CONTROL"
    command: Literal["NEXT_SLIDE", "PREV_SLIDE", "GOTO_SLIDE", "END_SESSION"]
    index: Optional[int] = None


# Server → Client messages

class ServerReady(BaseModel):
    """Server ready message."""
    type: Literal["SERVER_READY"] = "SERVER_READY"
    sessionId: str


class ServerTranscript(BaseModel):
    """Server transcript message."""
    type: Literal["SERVER_TRANSCRIPT"] = "SERVER_TRANSCRIPT"
    role: Literal["user", "assistant"]
    text: str
    final: bool = False


class ServerAudio(BaseModel):
    """Server audio chunk message."""
    type: Literal["SERVER_AUDIO"] = "SERVER_AUDIO"
    data: str  # base64 encoded audio
    sequence: int


class ServerSlideEvent(BaseModel):
    """Server slide event message."""
    type: Literal["SERVER_SLIDE_EVENT"] = "SERVER_SLIDE_EVENT"
    event: Literal["SLIDE_NEXT", "SLIDE_PREV", "SLIDE_JUMP", "SLIDE_RESTORE"]
    index: int


class ServerState(BaseModel):
    """Server state message."""
    type: Literal["SERVER_STATE"] = "SERVER_STATE"
    currentSlideIndex: int
    primarySlideIndex: int
    slideCursor: int


class ServerInterrupt(BaseModel):
    """Server interrupt message."""
    type: Literal["SERVER_INTERRUPT"] = "SERVER_INTERRUPT"


class ServerEnd(BaseModel):
    """Server end message."""
    type: Literal["SERVER_END"] = "SERVER_END"
    reason: str


