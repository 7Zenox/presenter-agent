"""ADK tools for slide navigation and memory management."""
from typing import Dict, Optional
from app.session import SlideManager, MemoryManager


# Global session-to-manager mapping
slide_manager_by_session: Dict[str, SlideManager] = {}
memory_manager_by_session: Dict[str, MemoryManager] = {}


def get_mgrs(session_id: str) -> tuple[SlideManager, MemoryManager]:
    """Get managers for a session."""
    slide_mgr = slide_manager_by_session.get(session_id)
    mem_mgr = memory_manager_by_session.get(session_id)
    if not slide_mgr or not mem_mgr:
        raise ValueError(f"Session {session_id} not found")
    return slide_mgr, mem_mgr


def register_session(session_id: str, slide_manager: SlideManager, memory_manager: MemoryManager):
    """Register a session with its managers."""
    slide_manager_by_session[session_id] = slide_manager
    memory_manager_by_session[session_id] = memory_manager


def unregister_session(session_id: str):
    """Unregister a session."""
    slide_manager_by_session.pop(session_id, None)
    memory_manager_by_session.pop(session_id, None)


def get_current_slide(session_id: str) -> Dict:
    """Return current slide JSON."""
    slides, _ = get_mgrs(session_id)
    slide = slides.current()
    if not slide:
        return {"error": "No current slide"}
    return {
        "id": slide.id,
        "title": slide.title,
        "bullets": slide.bullets,
        "current_index": slides.current_index
    }


def navigate_slides(session_id: str, action: str, index: Optional[int] = None) -> Dict:
    """
    Navigate slides. action in ["next", "prev", "jump", "restore"].
    """
    slides, _ = get_mgrs(session_id)
    
    if action == "next":
        slides.next()
    elif action == "prev":
        slides.prev()
    elif action == "jump" and index is not None:
        slides.jump_to(index)
    elif action == "restore":
        slides.restore()
    else:
        return {"error": f"Invalid action: {action}"}
    
    return {
        "current_index": slides.current_index,
        "primary_index": slides.primary_index,
        "action": action
    }


def get_slide_content(session_id: str, index: int) -> Dict:
    """Get content of a specific slide."""
    slides, _ = get_mgrs(session_id)
    slide = slides.get_slide(index)
    if not slide:
        return {"error": f"Slide {index} not found"}
    return {
        "id": slide.id,
        "title": slide.title,
        "bullets": slide.bullets
    }


def add_memory(session_id: str, role: str, text: str) -> None:
    """Add one utterance to rolling memory."""
    _, mem = get_mgrs(session_id)
    mem.add_turn(role, text)


def summarize_memory(session_id: str, model=None) -> str:
    """Summarize memory when it gets too long."""
    _, mem = get_mgrs(session_id)
    if not mem.needs_summary():
        return mem.summary
    
    # This will be called with a model instance
    if model:
        import asyncio
        if asyncio.iscoroutinefunction(mem.summarize):
            return asyncio.run(mem.summarize(model))
        else:
            return mem.summarize(model)
    
    return mem.summary




