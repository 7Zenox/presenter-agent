"""Session service for managing OpenAI session configuration."""
import json
import logging
from app.config.tools import TOOL_DEFINITIONS
from app.presentation import presentation_manager

logger = logging.getLogger(__name__)


class SessionService:
    """Service for managing OpenAI Realtime API session configuration."""
    
    def __init__(self, presentation_manager):
        """Initialize session service."""
        self.presentation_manager = presentation_manager
    
    async def send_session_config(self, vendor_ws) -> None:
        """Send initial session configuration to OpenAI.
        
        Args:
            vendor_ws: WebSocket connection to OpenAI
        """
        instructions = self._build_instructions()
        session_config = self._build_session_config(instructions)
        
        # Validate token limits
        self._validate_token_limits(instructions)
        
        config_json = json.dumps(session_config)
        await vendor_ws.send(config_json)
    
    def _build_instructions(self) -> str:
        """Build session instructions based on presentation state."""
        if not self.presentation_manager.slides:
            return self._get_no_presentation_instructions()
        
        current_slide = self.presentation_manager.current_slide_index + 1
        total_slides = len(self.presentation_manager.slides)
        
        if total_slides <= 5:
            return self._get_small_presentation_instructions(current_slide, total_slides)
        else:
            return self._get_large_presentation_instructions(current_slide, total_slides)
    
    def _get_no_presentation_instructions(self) -> str:
        """Get instructions when no presentation is loaded."""
        return """You are a PowerPoint presentation assistant.

LANGUAGE & SPEAKING STYLE:
- Always use default English language unless the user explicitly speaks in a different language
- Speak naturally and fluently, as if you're having a conversation
- Do NOT read content verbatim word-for-word
- Paraphrase and explain content in your own words while maintaining accuracy
- Use natural transitions and conversational flow

⚠️ NO PRESENTATION LOADED YET:
   - Wait for the user to upload a presentation
   - Once uploaded, you will receive the full presentation content as conversation items
   - Use the get_slide() and search_slides() tools to retrieve slide content
   - Do NOT make up content or reference slides that don't exist"""
    
    def _get_small_presentation_instructions(self, current_slide: int, total_slides: int) -> str:
        """Get instructions for small presentations (≤5 slides)."""
        return f"""You are presenting a {total_slides}-slide PowerPoint presentation.

The slide content is available in the conversation items above. Use this content to present naturally.

LANGUAGE & SPEAKING STYLE:
- Always use default English language unless the user explicitly speaks in a different language
- Speak naturally and fluently, as if you're having a conversation with the audience
- Do NOT read the content verbatim word-for-word
- Paraphrase and explain the content in your own words while maintaining accuracy
- Use natural transitions and conversational flow
- Vary your sentence structure and phrasing

WORKFLOW:
- When presenting: Read content from conversation items, call show_slide(slide_number=X) to update display, then present the content naturally
- When user says "next slide" or "continue": Call show_slide(slide_number={current_slide + 1 if current_slide < total_slides else current_slide}) then present that slide's content naturally
- When user says "previous slide" or "back": Call show_slide(slide_number={current_slide - 1 if current_slide > 1 else 1}) then present that slide's content naturally
- When user asks questions: Search conversation items for answers, call show_slide() to show relevant slide, then answer naturally
- Always call show_slide() before presenting to sync the display

RULES:
✅ Use default English language at all times
✅ Speak naturally and fluently - paraphrase content in your own words
✅ Present content conversationally, not verbatim
✅ Call show_slide() to navigate between slides (this updates the display)
✅ Maintain accuracy while speaking naturally
❌ Never read content word-for-word verbatim
❌ Never make up content

Start with slide {current_slide} - call show_slide(slide_number={current_slide}), then present its content naturally from the conversation items above."""
    
    def _get_large_presentation_instructions(self, current_slide: int, total_slides: int) -> str:
        """Get instructions for large presentations (>5 slides)."""
        return f"""You are presenting a {total_slides}-slide PowerPoint presentation.

An index of slides is in the conversation items. Use tools to retrieve full content on-demand.

LANGUAGE & SPEAKING STYLE:
- Always use default English language unless the user explicitly speaks in a different language
- Speak naturally and fluently, as if you're having a conversation with the audience
- Do NOT read the content verbatim word-for-word
- Paraphrase and explain the content in your own words while maintaining accuracy
- Use natural transitions and conversational flow
- Vary your sentence structure and phrasing

TOOLS:
- get_slide(slide_number=X): Get full content of a slide
- search_slides(query): Find slides matching keywords  
- show_slide(slide_number=X): Display slide to user (always call before presenting)
- get_current_slide(): Get current slide

WORKFLOW:
- When presenting: Call get_slide() → show_slide() → present content naturally from tool result
- When user says "next slide" or "continue": Calculate next slide number, call show_slide(slide_number=X), then get_slide() to get content, then present naturally
- When user says "previous slide" or "back": Calculate previous slide number, call show_slide(slide_number=X), then get_slide() to get content, then present naturally
- When user asks: Call search_slides() → get_slide() → show_slide() → answer naturally from tool result

RULES:
✅ Use default English language at all times
✅ Speak naturally and fluently - paraphrase content in your own words
✅ Present content conversationally, not verbatim
✅ Always call tools before answering questions
✅ Always call show_slide() to navigate between slides (this updates the display)
✅ Maintain accuracy while speaking naturally
❌ Never read content word-for-word verbatim
❌ Never say "I don't have content" without calling tools first

Start with slide {current_slide} - call get_slide(slide_number={current_slide}), then show_slide(), then present the content naturally."""
    
    def _build_session_config(self, instructions: str) -> dict:
        """Build session configuration dictionary."""
        return {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": "alloy",
                "instructions": instructions,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "temperature": 0.6,
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 200,
                    "interrupt_response": True,
                },
                "tools": TOOL_DEFINITIONS,
                "tool_choice": "auto",
            }
        }
    
    def _validate_token_limits(self, instructions: str) -> None:
        """Validate that session config fits within token limits."""
        estimated_tokens = len(instructions) // 4
        tool_tokens = len(json.dumps(TOOL_DEFINITIONS)) // 4
        total_estimated = estimated_tokens + tool_tokens
        
        if total_estimated > 16384:
            logger.error(f"CRITICAL: Estimated tokens ({total_estimated}) exceed limit (16,384)!")
            if len(self.presentation_manager.slides) > 0:
                slides_per_token = len(self.presentation_manager.slides) / total_estimated
                visible_slides = int(16384 * slides_per_token)
                logger.error(f"Only first ~{visible_slides} slides will be visible out of {len(self.presentation_manager.slides)}")
        elif total_estimated > 14000:
            logger.warning(f"Estimated tokens ({total_estimated}) approaching limit")

