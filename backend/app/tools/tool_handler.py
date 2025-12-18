"""Tool call handler for OpenAI function calls."""
import json
import re
import logging
from typing import Dict, Any
from app.presentation import presentation_manager

logger = logging.getLogger(__name__)


class ToolHandler:
    """Handles tool/function calls from OpenAI."""
    
    def __init__(self, presentation_manager):
        """Initialize tool handler with presentation manager."""
        self.presentation_manager = presentation_manager
    
    async def handle_tool_call(
        self, 
        vendor_ws, 
        client_ws, 
        item: dict
    ) -> None:
        """Handle a tool/function call from OpenAI.
        
        Args:
            vendor_ws: WebSocket connection to OpenAI
            client_ws: WebSocket connection to client
            item: Tool call item from OpenAI
        """
        function_name = item.get("name", "")
        call_id = item.get("call_id", "")
        arguments_str = item.get("arguments", "{}")
        
        # Parse arguments
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            arguments = {}
            logger.warning(f"Failed to parse arguments: {arguments_str}")
        
        # Execute tool function
        result = None
        try:
            result = await self._execute_tool(function_name, arguments, client_ws)
        except Exception as e:
            logger.error(f"Error executing tool {function_name}: {e}")
            result = {"error": str(e)}
        
        # Send tool result back to OpenAI
        tool_result_message = {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result),
            }
        }
        
        await vendor_ws.send(json.dumps(tool_result_message))
        
        # Request OpenAI to continue with the tool result
        continue_message = {
            "type": "response.create",
        }
        await vendor_ws.send(json.dumps(continue_message))
    
    async def _execute_tool(
        self, 
        function_name: str, 
        arguments: dict, 
        client_ws
    ) -> Dict[str, Any]:
        """Execute a specific tool function.
        
        Args:
            function_name: Name of the tool function
            arguments: Parsed arguments for the tool
            client_ws: WebSocket connection to client for notifications
            
        Returns:
            Tool execution result
        """
        if function_name == "navigate_slide":
            return await self._handle_navigate_slide(arguments, client_ws)
        elif function_name == "get_slide_content":
            return self._handle_get_slide_content(arguments)
        elif function_name == "get_current_slide":
            return self._handle_get_current_slide()
        elif function_name == "get_slide":
            return self._handle_get_slide(arguments)
        elif function_name == "search_slides":
            return self._handle_search_slides(arguments)
        elif function_name == "show_slide":
            return await self._handle_show_slide(arguments, client_ws)
        else:
            return {"error": f"Unknown function: {function_name}"}
    
    async def _handle_navigate_slide(self, arguments: dict, client_ws) -> Dict[str, Any]:
        """Handle navigate_slide tool call."""
        action = arguments.get("action")
        slide_index = arguments.get("slide_index")
        nav_result = self.presentation_manager.navigate_to_slide(action, slide_index)
        
        if "error" not in nav_result:
            slide_data = nav_result.get("slide", {})
            current_idx = nav_result.get("current_slide", 0)
            
            result = {
                "success": True,
                "slide_number": current_idx + 1,
                "title": slide_data.get("title", ""),
                "content": slide_data.get("content", ""),
                "notes": slide_data.get("notes", ""),
                "total_slides": nav_result.get("total_slides", 0),
                "message": f"Now on slide {current_idx + 1}. READ THE CONTENT ABOVE OUT LOUD."
            }
            
            # Notify client of slide change
            await client_ws.send_json({
                "type": "slide_changed",
                "slide_index": current_idx,
                "total_slides": nav_result.get("total_slides", 0),
                "slide": slide_data,
            })
            return result
        else:
            return nav_result
    
    def _handle_get_slide_content(self, arguments: dict) -> Dict[str, Any]:
        """Handle get_slide_content tool call."""
        slide_index = arguments.get("slide_index")
        result = self.presentation_manager.get_slide_content(slide_index)
        if "error" in result:
            logger.warning(f"Error getting slide {slide_index}: {result.get('error')}")
        return result
    
    def _handle_get_current_slide(self) -> Dict[str, Any]:
        """Handle get_current_slide tool call."""
        return self.presentation_manager.get_current_slide()
    
    def _handle_get_slide(self, arguments: dict) -> Dict[str, Any]:
        """Handle get_slide tool call."""
        slide_number = arguments.get("slide_number")
        if slide_number is None:
            logger.error("get_slide called without slide_number")
            return {"error": "slide_number is required"}
        
        slide_index = slide_number - 1
        if slide_index < 0 or slide_index >= len(self.presentation_manager.slides):
            logger.error(f"Invalid slide_number {slide_number}")
            return {"error": f"Invalid slide number {slide_number}. Valid range: 1-{len(self.presentation_manager.slides)}"}
        
        slide_data = self.presentation_manager.get_slide_content(slide_index)
        if "error" not in slide_data:
            slide_data["slide_number"] = slide_number
        return slide_data
    
    def _handle_search_slides(self, arguments: dict) -> Dict[str, Any]:
        """Handle search_slides tool call."""
        query = arguments.get("query", "").lower().strip()
        
        if not query:
            logger.warning("search_slides called without query")
            return {"error": "query is required"}
        
        # Extract keywords from query
        stop_words = [
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
            'can', 'could', 'may', 'might', 'must', 'shall', 'what', 'who', 'where',
            'when', 'why', 'how', 'which', 'about', 'tell', 'me', 'show'
        ]
        
        keywords = [
            word for word in re.findall(r'\b\w+\b', query.lower())
            if word not in stop_words
        ]
        
        if not keywords:
            keywords = query.split()
        
        # Search slides
        matching_slides = []
        for slide in self.presentation_manager.slides:
            slide_num = slide['index'] + 1
            title = slide.get('title', '').lower()
            content = slide.get('content', '').lower()
            
            # Count matches
            title_matches = sum(1 for kw in keywords if kw in title)
            content_matches = sum(1 for kw in keywords if kw in content)
            score = title_matches * 3 + content_matches
            
            if score > 0:
                matching_slides.append({
                    "slide_number": slide_num,
                    "title": slide.get('title', ''),
                    "content": slide.get('content', ''),
                    "score": score
                })
        
        # Sort by score
        matching_slides.sort(key=lambda x: x['score'], reverse=True)
        
        result = {
            "query": query,
            "total_matches": len(matching_slides),
            "slides": matching_slides[:3]  # Return top 3 matches
        }
        
        if not matching_slides:
            logger.warning(f"No matches found for query: {query}")
        
        return result
    
    async def _handle_show_slide(self, arguments: dict, client_ws) -> Dict[str, Any]:
        """Handle show_slide tool call."""
        slide_number = arguments.get("slide_number")
        if slide_number is None:
            logger.error("show_slide called without slide_number")
            return {"error": "slide_number is required"}
        
        slide_index = slide_number - 1
        
        if slide_index < 0 or slide_index >= len(self.presentation_manager.slides):
            logger.error(f"Invalid slide_number {slide_number}")
            return {"error": f"Invalid slide number {slide_number}. Valid range: 1-{len(self.presentation_manager.slides)}"}
        
        nav_result = self.presentation_manager.navigate_to_slide("jump", slide_index)
        if "error" in nav_result:
            logger.error(f"Navigation error: {nav_result.get('error')}")
            return nav_result
        
        result = {
            "success": True,
            "slide_number": slide_number,
            "slide_index": slide_index,
            "message": f"Switched to slide {slide_number}"
        }
        
        # Notify client of slide change
        slide_data = nav_result.get("slide", {})
        if "index" not in slide_data:
            slide_data["index"] = slide_index
        
        await client_ws.send_json({
            "type": "slide_changed",
            "slide_index": slide_index,
            "total_slides": nav_result.get("total_slides", 0),
            "slide": slide_data,
        })
        
        return result

