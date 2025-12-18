"""Conversation service for managing OpenAI conversation context."""
import json
import asyncio
import logging
from app.presentation import presentation_manager

logger = logging.getLogger(__name__)


class ConversationService:
    """Service for managing conversation context with OpenAI."""
    
    def __init__(self, presentation_manager):
        """Initialize conversation service."""
        self.presentation_manager = presentation_manager
    
    async def add_presentation_to_conversation(self, vendor_ws) -> None:
        """Add presentation data as conversation items per OpenAI Realtime API best practices.
        
        Per OpenAI docs (https://platform.openai.com/docs/guides/realtime-conversations):
        - Use conversation items for data context, not instructions
        - For small datasets: Add full content to conversation
        - For large datasets: Add index/summary, use tools for on-demand retrieval
        - Use role: "user" for data context (not "system" which is for instructions)
        
        Args:
            vendor_ws: WebSocket connection to OpenAI
        """
        if not self.presentation_manager.slides:
            return
        
        total_slides = len(self.presentation_manager.slides)
        
        # For small presentations, add full content to conversation
        # For larger ones, add index and rely on tools
        if total_slides <= 5:
            await self._add_full_content(vendor_ws)
        else:
            await self._add_index_only(vendor_ws, total_slides)
    
    async def _add_full_content(self, vendor_ws) -> None:
        """Add full slide content as conversation items."""
        for slide in self.presentation_manager.slides:
            slide_num = slide['index'] + 1
            title = slide.get('title', 'Untitled')
            content = slide.get('content', '').strip()
            notes = slide.get('notes', '').strip()
            
            slide_item = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",  # Data context uses "user" role per OpenAI docs
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"""SLIDE {slide_num}: {title}

Content:
{content if content else "(Visual slide)"}

{f'Notes: {notes}' if notes else ''}"""
                        }
                    ]
                }
            }
            await vendor_ws.send(json.dumps(slide_item))
            await asyncio.sleep(0.05)  # Small delay to avoid overwhelming the API
    
    async def _add_index_only(self, vendor_ws, total_slides: int) -> None:
        """Add slide index only, use tools for retrieval."""
        slides_summary = self.presentation_manager.get_all_slides_summary()
        
        index_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",  # Data context, not instructions
                "content": [
                    {
                        "type": "input_text",
                        "text": f"""PRESENTATION INDEX ({total_slides} slides):

{slides_summary}

Use get_slide(slide_number=X) tool to retrieve full content of any slide."""
                    }
                ]
            }
        }
        
        await vendor_ws.send(json.dumps(index_item))

