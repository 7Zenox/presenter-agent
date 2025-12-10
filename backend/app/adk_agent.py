"""ADK agent configuration for Gemini Live."""
from typing import Optional, Dict
from app.gemini_client import get_client, get_model_for_generate_content


SYSTEM_PROMPT = """You are a slide presenter and Q&A assistant.

You:
- Present one slide at a time.
- Use get_current_slide to know what is on the slide.
- Use navigate_slides to move: "next", "prev", "jump", "restore".
- If you temporarily jump to another slide to answer a question, you MUST call navigate_slides(..., "restore") after answering and continue from where you left off.
- Keep answers concise and aligned with the current slide.
- Use add_memory to record important user preferences or questions.
- Periodically call summarize_memory when conversation becomes long, then rely on the summary.
"""


def get_live_model():
    """Get a Gemini client and model name for text generation."""
    client = get_client()
    model_name = get_model_for_generate_content()
    return client, model_name


def create_agent_context(session_id: str, topic: str) -> Dict:
    """Create context for the agent."""
    return {
        "session_id": session_id,
        "topic": topic,
        "system_prompt": SYSTEM_PROMPT
    }
