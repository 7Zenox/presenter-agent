"""
PowerPoint presentation parser and tool handlers for the presenter agent.
"""
import json
from typing import Dict, List, Optional
from pptx import Presentation
import io
import logging

logger = logging.getLogger(__name__)


class PresentationManager:
    """Manages PowerPoint presentation state and operations."""
    
    def __init__(self):
        self.presentation: Optional[Presentation] = None
        self.slides: List[Dict] = []
        self.current_slide_index: int = 0
    
    def load_presentation(self, pptx_bytes: bytes) -> Dict:
        """Load a PowerPoint presentation from bytes."""
        try:
            # Clear any existing presentation data first
            logger.info("Clearing any existing presentation data...")
            self.presentation = None
            self.slides = []
            self.current_slide_index = 0
            
            # Load new presentation
            self.presentation = Presentation(io.BytesIO(pptx_bytes))
            self.slides = []
            
            for idx, slide in enumerate(self.presentation.slides):
                slide_data = {
                    "index": idx,
                    "title": self._extract_title(slide),
                    "content": self._extract_content(slide),
                    "notes": self._extract_notes(slide),
                }
                self.slides.append(slide_data)
            
            self.current_slide_index = 0
            
            # Log first slide to verify content
            if self.slides:
                first_slide = self.slides[0]
                logger.info(f"✅ Loaded NEW presentation with {len(self.slides)} slides")
                logger.info(f"   First slide title: '{first_slide['title']}'")
                logger.info(f"   First slide content (first 200 chars): '{first_slide['content'][:200]}'")
            else:
                logger.warning("⚠️ Loaded presentation but no slides found!")
            
            return {
                "success": True,
                "total_slides": len(self.slides),
                "slides": self.slides,
            }
        except Exception as e:
            logger.error(f"Error loading presentation: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
            }
    
    def _extract_title(self, slide) -> str:
        """Extract title from slide."""
        if slide.shapes.title:
            return slide.shapes.title.text.strip()
        return f"Slide {slide.slide_id}"
    
    def _extract_content(self, slide) -> str:
        """Extract all text content from slide."""
        content_parts = []
        
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                text = shape.text.strip()
                if text and text != slide.shapes.title.text if slide.shapes.title else True:
                    content_parts.append(text)
        
        return "\n".join(content_parts)
    
    def _extract_notes(self, slide) -> str:
        """Extract speaker notes from slide."""
        if slide.has_notes_slide:
            notes_slide = slide.notes_slide
            if notes_slide.notes_text_frame:
                return notes_slide.notes_text_frame.text.strip()
        return ""
    
    def get_current_slide(self) -> Dict:
        """Get current slide information."""
        if not self.slides or self.current_slide_index >= len(self.slides):
            return {"error": "No slides available"}
        
        slide = self.slides[self.current_slide_index].copy()
        slide["is_current"] = True
        return slide
    
    def navigate_to_slide(self, action: str, slide_index: Optional[int] = None) -> Dict:
        """Navigate to a slide.
        
        Args:
            action: "next", "prev", or "jump"
            slide_index: Required if action is "jump"
        """
        if not self.slides:
            return {"error": "No presentation loaded"}
        
        total_slides = len(self.slides)
        
        if action == "next":
            if self.current_slide_index < total_slides - 1:
                self.current_slide_index += 1
            else:
                return {"error": "Already on last slide"}
        
        elif action == "prev":
            if self.current_slide_index > 0:
                self.current_slide_index -= 1
            else:
                return {"error": "Already on first slide"}
        
        elif action == "jump":
            if slide_index is None:
                return {"error": "slide_index required for jump action"}
            if 0 <= slide_index < total_slides:
                self.current_slide_index = slide_index
            else:
                return {"error": f"Invalid slide index. Must be between 0 and {total_slides - 1}"}
        
        else:
            return {"error": f"Invalid action: {action}. Use 'next', 'prev', or 'jump'"}
        
        return {
            "success": True,
            "current_slide": self.current_slide_index,
            "total_slides": total_slides,
            "slide": self.get_current_slide(),
        }
    
    def get_slide_content(self, slide_index: int) -> Dict:
        """Get content of a specific slide."""
        if not self.slides:
            return {"error": "No presentation loaded"}
        
        if 0 <= slide_index < len(self.slides):
            slide = self.slides[slide_index].copy()
            slide["is_current"] = (slide_index == self.current_slide_index)
            return slide
        else:
            return {"error": f"Invalid slide index. Must be between 0 and {len(self.slides) - 1}"}
    
    def get_all_slides_summary(self) -> str:
        """Get complete JSON dump of all slides with full content for the AI."""
        if not self.slides:
            return "No presentation loaded."
        
        # Return JSON format with all slides - FULL CONTENT, NO SUMMARIES
        # Add slide_number (1-based) to each slide for clarity
        import json
        slides_with_number = []
        for slide in self.slides:
            slide_copy = slide.copy()
            slide_copy['slide_number'] = slide['index'] + 1  # 1-based slide number
            slides_with_number.append(slide_copy)
        
        slides_json = json.dumps(slides_with_number, indent=2)
        
        return f"""COMPLETE PRESENTATION DATA (JSON format):
Total slides: {len(self.slides)}

All slides with FULL content:
{slides_json}

Each slide contains:
- slide_number: 1-based slide number (slide 1, slide 2, etc.) - USE THIS for show_slide() tool
- index: 0-based index (for internal reference)
- title: Full slide title
- content: COMPLETE slide content (all text from the slide)
- notes: Speaker notes (if any)

You have access to ALL slide content above. Use this data to answer questions directly.
When you want to show a slide to the user, call show_slide(slide_number) where slide_number is the 1-based number."""
    
    def get_all_slides_json(self) -> str:
        """Get slides as JSON string for embedding in instructions."""
        import json
        if not self.slides:
            return "[]"
        # Add slide_number (1-based) to each slide for clarity
        slides_with_number = []
        for slide in self.slides:
            slide_copy = slide.copy()
            slide_copy['slide_number'] = slide['index'] + 1  # 1-based slide number
            slides_with_number.append(slide_copy)
        return json.dumps(slides_with_number, indent=2)


# Global presentation manager instance
presentation_manager = PresentationManager()

