"""Session management for slides and memory."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from app.models import Slide


class SlideManager:
    """Manages slide navigation state."""
    
    def __init__(self, slides: List[Slide]):
        self.slides = slides
        self.current_index = 0
        self.primary_index = 0  # Last "main" slide being presented
        self.stack: List[int] = []  # For jump-and-resume navigation
        self.cursors: Dict[int, int] = {i: 0 for i in range(len(slides))}
    
    def current(self) -> Optional[Slide]:
        """Get the current slide."""
        if 0 <= self.current_index < len(self.slides):
            return self.slides[self.current_index]
        return None
    
    def next(self):
        """Move to the next slide."""
        if self.current_index < len(self.slides) - 1:
            self.primary_index = self.current_index + 1
            self.current_index += 1
    
    def prev(self):
        """Move to the previous slide."""
        if self.current_index > 0:
            self.primary_index = self.current_index - 1
            self.current_index -= 1
    
    def jump_to(self, idx: int):
        """Jump to a specific slide, saving current position."""
        if 0 <= idx < len(self.slides):
            self.stack.append(self.current_index)
            self.current_index = idx
    
    def restore(self):
        """Restore to the last slide before a jump."""
        if self.stack:
            self.current_index = self.stack.pop()
    
    def get_slide(self, idx: int) -> Optional[Slide]:
        """Get a slide by index."""
        if 0 <= idx < len(self.slides):
            return self.slides[idx]
        return None


class MemoryManager:
    """Manages conversation memory with summarization."""
    
    def __init__(self, max_chars: int = 8000):
        self.summary: str = ""
        self.recent: List[Dict[str, str]] = []
        self.max_chars = max_chars
    
    def add_turn(self, role: str, text: str):
        """Add a conversation turn."""
        self.recent.append({"role": role, "content": text})
    
    def length(self) -> int:
        """Calculate total memory length."""
        recent_length = sum(len(m["content"]) for m in self.recent)
        return len(self.summary) + recent_length
    
    def needs_summary(self) -> bool:
        """Check if summarization is needed."""
        return self.length() > self.max_chars
    
    async def summarize(self, client=None, model_name=None) -> str:
        """Summarize memory using Gemini model."""
        if not self.needs_summary():
            return self.summary
        
        from app.gemini_client import get_client, get_model_for_generate_content
        
        if client is None:
            client = get_client()
        if model_name is None:
            model_name = get_model_for_generate_content()
        
        prompt = (
            "Summarize this conversation in <= 300 tokens, "
            "focusing on questions about the slides and what has been explained so far.\n\n"
            f"CURRENT SUMMARY:\n{self.summary}\n\nRECENT MESSAGES:\n"
        )
        
        recent_text = "\n".join(
            f"{m['role']}: {m['content']}" for m in self.recent
        )
        prompt += recent_text
        
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            new_summary = response.text
            self.summary = new_summary
            self.recent = []
            return self.summary
        except Exception as e:
            # If summarization fails, keep existing memory
            print(f"Summarization error: {e}")
            return self.summary


