import asyncio
import os
import json
import logging
import time
import websockets
import traceback
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from app.presentation import presentation_manager

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_REALTIME_URL = os.getenv(
    "OPENAI_REALTIME_URL",
    "wss://api.openai.com/v1/realtime?model=gpt-realtime"
)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Tool definitions for PowerPoint presentation
# Designed following ReAct (Reasoning and Acting) pattern principles
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "search_slides",
        "description": "Search through ALL slides to find information relevant to a query. This is your primary information retrieval tool. Extract key terms from the user's question and search for matching slides. Returns up to 3 most relevant slides with their full content. Use this whenever you need to find information from the presentation.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query extracted from user's question. Use 2-5 key terms. Examples: 'investors', 'product features', 'pricing model', 'team members', 'company background'"
                }
            },
            "required": ["query"]
        }
    },
    {
        "type": "function",
        "name": "show_slide",
        "description": "Navigate to and display a specific slide to the user. Use this tool to move between slides. When user says 'next slide', call this with the next slide number. When user says 'previous slide', call this with the previous slide number. The frontend will automatically scroll to the displayed slide. Always call this before presenting slide content to sync the display.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_number": {
                    "type": "integer",
                    "description": "Slide number (1-based). Slide 1 = 1, Slide 2 = 2, etc. Use this to navigate: next slide = current + 1, previous slide = current - 1."
                }
            },
            "required": ["slide_number"]
        }
    },
    {
        "type": "function",
        "name": "navigate_slide",
        "description": "Navigate to next/previous slide or jump to specific index",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["next", "prev", "jump"],
                    "description": "Navigation action"
                },
                "slide_index": {
                    "type": "integer",
                    "description": "Slide index (0-based) - required for 'jump'"
                }
            },
            "required": ["action"]
        }
    },
    {
        "type": "function",
        "name": "get_slide_content",
        "description": "Get content of a specific slide by index (0-based)",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_index": {
                    "type": "integer",
                    "description": "Slide index (0-based)"
                }
            },
            "required": ["slide_index"]
        }
    },
    {
        "type": "function",
        "name": "get_current_slide",
        "description": "Get the current slide information",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "type": "function",
        "name": "get_slide",
        "description": "Get the FULL content of a specific slide by slide number. Use this when you need detailed information from a slide. The summaries in your instructions only show previews - call this tool to get complete slide content including all text, bullet points, and notes.",
        "parameters": {
            "type": "object",
            "properties": {
                "slide_number": {
                    "type": "integer",
                    "description": "Slide number (1-based). Slide 1 = 1, Slide 2 = 2, etc."
                }
            },
            "required": ["slide_number"]
        }
    },
]

# Headers for OpenAI connection (as dict, matching reference implementation)
def get_openai_headers():
    """Get headers for OpenAI WebSocket connection."""
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "openai-beta": "realtime=v1",  # Lowercase to match OpenAI spec
    }


async def send_error_safe(ws: WebSocket, error_type: str, error_message: str):
    """Safely send error messages to the client WebSocket as JSON."""
    try:
        await ws.send_json({
            "type": "error",
            "error": error_message,
            "error_type": error_type
        })
    except Exception as e:
        logger.error(f"Error sending error message to client: {e}")


async def handle_tool_call(vendor_ws, client_ws, item: dict):
    """Handle a tool/function call from OpenAI."""
    function_name = item.get("name", "")
    call_id = item.get("call_id", "")  # Use call_id, not id
    arguments_str = item.get("arguments", "{}")
    
    logger.info(f"🔧🔧🔧 HANDLING TOOL CALL 🔧🔧🔧")
    logger.info(f"   Function: {function_name}")
    logger.info(f"   Call ID: {call_id}")
    logger.info(f"   Arguments: {arguments_str}")
    
    # Parse arguments
    try:
        arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
    except json.JSONDecodeError:
        arguments = {}
        logger.warning(f"Failed to parse arguments: {arguments_str}")
    
    # Execute tool function
    result = None
    try:
        if function_name == "navigate_slide":
            action = arguments.get("action")
            slide_index = arguments.get("slide_index")
            nav_result = presentation_manager.navigate_to_slide(action, slide_index)
            
            if "error" not in nav_result:
                # Get full slide content to include in result
                slide_data = nav_result.get("slide", {})
                current_idx = nav_result.get("current_slide", 0)
                
                # Build result with explicit content for AI to use
                result = {
                    "success": True,
                    "slide_number": current_idx + 1,  # 1-based for AI
                    "title": slide_data.get("title", ""),
                    "content": slide_data.get("content", ""),
                    "notes": slide_data.get("notes", ""),
                    "total_slides": nav_result.get("total_slides", 0),
                    "message": f"Now on slide {current_idx + 1}. READ THE CONTENT ABOVE OUT LOUD."
                }
                
                logger.info(f"   📍 Navigated to slide {current_idx + 1}")
                logger.info(f"   📄 Title: {result['title']}")
                logger.info(f"   📄 Content length: {len(result['content'])} chars")
                
                # Notify client of slide change
                await client_ws.send_json({
                    "type": "slide_changed",
                    "slide_index": current_idx,
                    "total_slides": nav_result.get("total_slides", 0),
                    "slide": slide_data,
                })
            else:
                result = nav_result
        
        elif function_name == "get_slide_content":
            slide_index = arguments.get("slide_index")
            logger.info(f"   📄 Getting content for slide {slide_index}")
            result = presentation_manager.get_slide_content(slide_index)
            if "error" not in result:
                logger.info(f"   ✅ Retrieved slide {slide_index}: '{result.get('title', 'N/A')}'")
                logger.info(f"   📝 Content preview: '{result.get('content', '')[:200]}...'")
            else:
                logger.warning(f"   ⚠️ Error getting slide {slide_index}: {result.get('error')}")
        
        elif function_name == "get_current_slide":
            result = presentation_manager.get_current_slide()
        
        elif function_name == "get_slide":
            slide_number = arguments.get("slide_number")
            logger.info(f"   📄 get_slide called with slide_number={slide_number}")
            if slide_number is None:
                result = {"error": "slide_number is required"}
                logger.error("   ❌ get_slide called without slide_number!")
            else:
                # Convert 1-based slide number to 0-based index
                slide_index = slide_number - 1
                if slide_index < 0 or slide_index >= len(presentation_manager.slides):
                    result = {"error": f"Invalid slide number {slide_number}. Valid range: 1-{len(presentation_manager.slides)}"}
                    logger.error(f"   ❌ Invalid slide_number {slide_number}")
                else:
                    slide_data = presentation_manager.get_slide_content(slide_index)
                    if "error" not in slide_data:
                        # Add slide_number for consistency
                        slide_data["slide_number"] = slide_number
                        result = slide_data
                        logger.info(f"   ✅ Retrieved full content for slide {slide_number}: '{slide_data.get('title', 'N/A')}'")
                        logger.info(f"   📝 Content length: {len(slide_data.get('content', ''))} chars")
                    else:
                        result = slide_data
        
        elif function_name == "search_slides":
            query = arguments.get("query", "").lower().strip()
            logger.info(f"   🔍 search_slides called with query: '{query}'")
            
            if not query:
                result = {"error": "query is required"}
                logger.warning("   ⚠️ search_slides called without query")
            else:
                # Extract keywords from query
                import re
                keywords = [word for word in re.findall(r'\b\w+\b', query.lower()) 
                           if word not in ['the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 
                                          'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
                                          'can', 'could', 'may', 'might', 'must', 'shall', 'what', 'who', 'where',
                                          'when', 'why', 'how', 'which', 'about', 'tell', 'me', 'show']]
                
                if not keywords:
                    keywords = query.split()
                
                logger.info(f"   🔑 Search keywords: {keywords}")
                
                # Search slides
                matching_slides = []
                for slide in presentation_manager.slides:
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
                
                if matching_slides:
                    top = matching_slides[0]
                    logger.info(f"   ✅ Found {len(matching_slides)} matches. Top: slide {top['slide_number']} - '{top['title']}' (score: {top['score']})")
                else:
                    logger.warning(f"   ⚠️ No matches found for: {keywords}")
        
        elif function_name == "show_slide":
            slide_number = arguments.get("slide_number")
            logger.info(f"   🎯 show_slide called with slide_number={slide_number}")
            if slide_number is None:
                result = {"error": "slide_number is required"}
                logger.error("   ❌ show_slide called without slide_number!")
            else:
                # Convert 1-based slide number to 0-based index
                slide_index = slide_number - 1
                logger.info(f"   📍 Converting slide_number {slide_number} to index {slide_index}")
                
                # Validate slide index
                if slide_index < 0 or slide_index >= len(presentation_manager.slides):
                    result = {"error": f"Invalid slide number {slide_number}. Valid range: 1-{len(presentation_manager.slides)}"}
                    logger.error(f"   ❌ Invalid slide_number {slide_number} (index {slide_index}), total slides: {len(presentation_manager.slides)}")
                else:
                    nav_result = presentation_manager.navigate_to_slide("jump", slide_index)
                    if "error" in nav_result:
                        result = nav_result
                        logger.error(f"   ❌ Navigation error: {nav_result.get('error')}")
                    else:
                        result = {
                            "success": True,
                            "slide_number": slide_number,
                            "slide_index": slide_index,
                            "message": f"Switched to slide {slide_number}"
                        }
                        # Notify client of slide change
                        slide_data = nav_result.get("slide", {})
                        # Ensure slide_data has index field
                        if "index" not in slide_data:
                            slide_data["index"] = slide_index
                        
                        logger.info(f"   📤 Sending slide_changed event to frontend:")
                        logger.info(f"      slide_index: {slide_index}")
                        logger.info(f"      slide_number: {slide_number}")
                        logger.info(f"      title: {slide_data.get('title', 'N/A')}")
                        logger.info(f"      total_slides: {nav_result.get('total_slides', 0)}")
                        
                        await client_ws.send_json({
                            "type": "slide_changed",
                            "slide_index": slide_index,
                            "total_slides": nav_result.get("total_slides", 0),
                            "slide": slide_data,
                        })
                        logger.info(f"   ✅ slide_changed event sent successfully")
        
        else:
            result = {"error": f"Unknown function: {function_name}"}
    
    except Exception as e:
        logger.error(f"Error executing tool {function_name}: {e}")
        result = {"error": str(e)}
    
    # Send tool result back to OpenAI
    logger.info(f"📤 Sending tool result back to OpenAI for {function_name} (call_id: {call_id})")
    tool_result_message = {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(result),
        }
    }
    
    await vendor_ws.send(json.dumps(tool_result_message))
    logger.info(f"✅ Tool result sent successfully for {function_name}")
    # Log full result for specific tools to verify content is being sent
    if function_name == "search_slides":
        logger.info(f"✅ search_slides result sent:")
        if isinstance(result, dict) and "slides" in result:
            logger.info(f"   Total matches: {result.get('total_matches', 0)}")
            for idx, slide in enumerate(result.get('slides', [])[:2]):
                logger.info(f"   Match {idx+1}: slide {slide.get('slide_number')} - '{slide.get('title')}' (score: {slide.get('score')})")
                logger.info(f"      Content preview: {slide.get('content', '')[:200]}...")
    elif function_name == "get_slide":
        logger.info(f"✅ get_slide result sent:")
        if isinstance(result, dict) and "error" not in result:
            logger.info(f"   Slide {result.get('slide_number', 'N/A')}: '{result.get('title', 'N/A')}'")
            logger.info(f"   Full content length: {len(result.get('content', ''))} chars")
            logger.info(f"   Content preview: {result.get('content', '')[:300]}...")
        else:
            logger.warning(f"   ⚠️ Error retrieving slide: {result.get('error', 'Unknown error')}")
    elif function_name == "get_slide_content":
        logger.info(f"✅ Tool result sent for {function_name}:")
        logger.info(f"   Title: '{result.get('title', 'N/A') if isinstance(result, dict) else 'N/A'}'")
        logger.info(f"   Content length: {len(str(result.get('content', ''))) if isinstance(result, dict) else 0} chars")
        logger.info(f"   Full result (first 500 chars): {json.dumps(result)[:500]}...")
    else:
        logger.info(f"✅ Tool result sent: {json.dumps(result)[:200]}")
    
    # Request OpenAI to continue with the tool result
    continue_message = {
        "type": "response.create",
    }
    await vendor_ws.send(json.dumps(continue_message))


async def add_presentation_to_conversation(vendor_ws):
    """Add presentation data as conversation items per OpenAI Realtime API best practices.
    
    Per OpenAI docs (https://platform.openai.com/docs/guides/realtime-conversations):
    - Use conversation items for data context, not instructions
    - For small datasets: Add full content to conversation
    - For large datasets: Add index/summary, use tools for on-demand retrieval
    - Use role: "user" for data context (not "system" which is for instructions)
    """
    if not presentation_manager.slides:
        logger.warning("   ⚠️ No slides to add to conversation")
        return
    
    total_slides = len(presentation_manager.slides)
    
    # Per OpenAI docs: For small presentations, add full content to conversation
    # For larger ones, add index and rely on tools
    if total_slides <= 5:
        # Small presentation: Add full content as conversation items
        # Use role: "user" per OpenAI docs - this is data context, not instructions
        logger.info(f"   📚 Adding FULL content of {total_slides} slides to conversation (small presentation)")
        
        for slide in presentation_manager.slides:
            slide_num = slide['index'] + 1
            title = slide.get('title', 'Untitled')
            content = slide.get('content', '').strip()
            notes = slide.get('notes', '').strip()
            
            # Create conversation item with slide data
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
        
        logger.info(f"   ✅ Added full content of {total_slides} slides to conversation")
        
    else:
        # Large presentation: Add index only, use tools for retrieval
        # Per OpenAI docs: Use tools for on-demand data retrieval
        logger.info(f"   📋 Adding slides INDEX to conversation ({total_slides} slides - using tools for content)")
        
        slides_summary = presentation_manager.get_all_slides_summary()
        
        # Add index as a conversation item (role: "user" for data context)
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
        logger.info(f"   ✅ Added slides index to conversation - tools will fetch content on-demand")


async def send_session_config(vendor_ws):
    """Send initial session configuration to OpenAI."""
    # Get complete presentation JSON dump (FULL CONTENT, NO SUMMARIES)
    presentation_data = presentation_manager.get_all_slides_summary()
    
    # CRITICAL: Verify presentation data is not empty
    if presentation_manager.slides and len(presentation_data) < 100:
        logger.error(f"⚠️⚠️⚠️ WARNING: Presentation data seems too short ({len(presentation_data)} chars)!")
        logger.error(f"   This might indicate the JSON is not being generated correctly!")
    
    # Log what presentation content is being sent - VERY EXPLICITLY
    logger.info("=" * 80)
    logger.info("📊 SENDING SESSION CONFIG TO OPENAI")
    logger.info("=" * 80)
    logger.info(f"   Total slides: {len(presentation_manager.slides)}")
    logger.info(f"   Presentation data length: {len(presentation_data)} characters")
    
    if presentation_manager.slides:
        first_slide = presentation_manager.slides[0]
        logger.info(f"   ✅ First slide title: '{first_slide.get('title', 'N/A')}'")
        logger.info(f"   ✅ First slide content (first 500 chars): '{first_slide.get('content', '')[:500]}...'")
        logger.info(f"   ✅ First slide full content length: {len(first_slide.get('content', ''))} chars")
        # Also log a few key words to verify it's the right presentation
        content_lower = first_slide.get('content', '').lower()
        if 'synthio' in content_lower:
            logger.info("   ✅ VERIFIED: Content contains 'synthio' - this is the synthio labs presentation")
        elif 'energy' in content_lower or 'grid' in content_lower:
            logger.warning("   ⚠️  WARNING: Content contains 'energy' or 'grid' - this might be the OLD presentation!")
        elif 'shuttle' in content_lower or 'mobility' in content_lower:
            logger.warning("   ⚠️  WARNING: Content contains 'shuttle' or 'mobility' - this might be the OLD presentation!")
        
        # Log a sample of the JSON data being sent
        import json
        if presentation_manager.slides:
            sample_slide = presentation_manager.slides[0].copy()
            sample_slide['slide_number'] = sample_slide['index'] + 1
            logger.info(f"   📄 Sample slide JSON (first 1000 chars): {json.dumps(sample_slide, indent=2)[:1000]}...")
    else:
        logger.warning("   ⚠️ No slides loaded in presentation_manager!")
        logger.warning("   ⚠️ Presentation data will be empty!")
    
    logger.info("=" * 80)
    
    # Check if presentation is loaded
    if not presentation_manager.slides:
        logger.warning("⚠️ WARNING: No presentation loaded! Sending config without presentation data.")
        instructions = """You are a PowerPoint presentation assistant. 

⚠️ NO PRESENTATION LOADED YET:
   - Wait for the user to upload a presentation
   - Once uploaded, you will receive the full presentation content as conversation items
   - Use the get_slide() and search_slides() tools to retrieve slide content
   - Do NOT make up content or reference slides that don't exist"""
    else:
        # CONCISE instructions per OpenAI docs - data goes in conversation items, not here
        current_slide = presentation_manager.current_slide_index + 1
        total_slides = len(presentation_manager.slides)
        
        # Per OpenAI docs: Instructions should be concise, focus on behavior
        # Data context is in conversation items (added separately)
        if total_slides <= 5:
            # Small presentation: Content is in conversation items, reference it directly
            instructions = f"""You are presenting a {total_slides}-slide PowerPoint presentation.

The slide content is available in the conversation items above. Read the content directly from those items.

WORKFLOW:
- When presenting: Read content from conversation items, call show_slide(slide_number=X) to update display
- When user says "next slide" or "continue": Call show_slide(slide_number={current_slide + 1 if current_slide < total_slides else current_slide}) then read that slide's content
- When user says "previous slide" or "back": Call show_slide(slide_number={current_slide - 1 if current_slide > 1 else 1}) then read that slide's content
- When user asks questions: Search conversation items for answers, call show_slide() to show relevant slide
- Always call show_slide() before presenting to sync the display

RULES:
✅ Read content directly from conversation items
✅ Call show_slide() to navigate between slides (this updates the display)
✅ Use exact content from conversation items
❌ Never make up content

Start with slide {current_slide} - call show_slide(slide_number={current_slide}), then read its content from the conversation items above."""
        else:
            # Large presentation: Use tools for on-demand retrieval
            instructions = f"""You are presenting a {total_slides}-slide PowerPoint presentation.

An index of slides is in the conversation items. Use tools to retrieve full content on-demand.

TOOLS:
- get_slide(slide_number=X): Get full content of a slide
- search_slides(query): Find slides matching keywords  
- show_slide(slide_number=X): Display slide to user (always call before presenting)
- get_current_slide(): Get current slide

WORKFLOW:
- When presenting: Call get_slide() → show_slide() → read content from tool result
- When user says "next slide" or "continue": Calculate next slide number, call show_slide(slide_number=X), then get_slide() to get content, then present
- When user says "previous slide" or "back": Calculate previous slide number, call show_slide(slide_number=X), then get_slide() to get content, then present
- When user asks: Call search_slides() → get_slide() → show_slide() → answer from tool result

RULES:
✅ Always call tools before answering questions
✅ Always call show_slide() to navigate between slides (this updates the display)
✅ Use exact content from tool results
❌ Never say "I don't have content" without calling tools first

Start with slide {current_slide} - call get_slide(slide_number={current_slide}), then show_slide(), then present."""
    
    session_config = {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],  # Both text and audio for better content processing
            "voice": "alloy",
            "instructions": instructions,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "temperature": 0,  # Deterministic - follow instructions strictly
            "input_audio_transcription": {
                "model": "whisper-1"
            },
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 200,
                "interrupt_response": True,  # Allow user to interrupt assistant's responses
            },
            "tools": TOOL_DEFINITIONS,
            "tool_choice": "auto",  # Auto at session level - use 'required' only in response.create
        }
    }
    
    config_json = json.dumps(session_config)
    
    # Estimate token count (rough: ~4 chars per token)
    estimated_tokens = len(instructions) // 4
    tool_tokens = len(json.dumps(TOOL_DEFINITIONS)) // 4
    total_estimated = estimated_tokens + tool_tokens
    
    logger.info(f"📤 Sending session config to OpenAI")
    logger.info(f"   Instructions length: {len(instructions)} chars (~{estimated_tokens} tokens)")
    logger.info(f"   Tools length: {len(json.dumps(TOOL_DEFINITIONS))} chars (~{tool_tokens} tokens)")
    logger.info(f"   Total estimated: ~{total_estimated} tokens")
    logger.info(f"   OpenAI limit: 16,384 tokens for instructions + tools")
    logger.info(f"   Presentation data included: {'YES' if presentation_manager.slides else 'NO'}")
    
    # Check for potential truncation (OpenAI Realtime API limit: 16,384 tokens)
    if total_estimated > 16384:
        logger.error(f"   ❌❌❌ CRITICAL: Estimated tokens ({total_estimated}) EXCEED limit (16,384)!")
        logger.error(f"   ❌❌❌ OpenAI will TRUNCATE instructions - AI will NOT see all slides!")
        # Calculate how many slides would fit
        if len(presentation_manager.slides) > 0:
            slides_per_token = len(presentation_manager.slides) / total_estimated
            visible_slides = int(16384 * slides_per_token)
            logger.error(f"   ❌❌❌ Only first ~{visible_slides} slides will be visible out of {len(presentation_manager.slides)}!")
    elif total_estimated > 14000:
        logger.warning(f"   ⚠️⚠️⚠️ WARNING: Estimated tokens ({total_estimated}) approaching limit!")
        logger.warning(f"   ⚠️⚠️⚠️ Consider using compact summaries (already implemented)")
    
    # CRITICAL: Verify slide count in instructions
    if presentation_manager.slides:
        slide_count_in_instructions = instructions.count('"slide_number":')
        logger.info(f"   🔍 Slide entries in instructions: {slide_count_in_instructions}")
        logger.info(f"   🔍 Expected slides: {len(presentation_manager.slides)}")
        if slide_count_in_instructions != len(presentation_manager.slides):
            logger.error(f"   ❌❌❌ MISMATCH: Instructions contain {slide_count_in_instructions} slides but {len(presentation_manager.slides)} slides exist!")
            logger.error(f"   ❌❌❌ This means some slides are missing from the AI's context!")
        else:
            logger.info(f"   ✅ All {len(presentation_manager.slides)} slides are present in instructions")
    
    if presentation_data and len(presentation_data) > 50000:
        logger.warning(f"   ⚠️ Presentation data is large ({len(presentation_data)} chars)")
        logger.warning(f"   ⚠️ Using compact summaries to fit within token limits")
    if presentation_manager.slides:
        logger.info(f"   Number of slides in data: {len(presentation_manager.slides)}")
        # Verify presentation_data is actually in instructions
        if presentation_data and presentation_data not in instructions:
            logger.error("⚠️⚠️⚠️ CRITICAL ERROR: Presentation data NOT found in instructions!")
            logger.error(f"   Instructions length: {len(instructions)}")
            logger.error(f"   Presentation data length: {len(presentation_data)}")
        else:
            logger.info(f"   ✅ Presentation data verified in instructions")
        # Log a snippet showing the actual JSON data
        if presentation_data:
            logger.info(f"   📄 Presentation data preview (first 500 chars): {presentation_data[:500]}...")
            # Check if slide 5 is mentioned in the data
            if '"slide_number": 5' in presentation_data or '"slide_number":5' in presentation_data:
                logger.info(f"   ✅ Slide 5 is present in presentation_data")
            else:
                logger.error(f"   ❌❌❌ Slide 5 NOT found in presentation_data!")
            # Count how many slide_number entries are in the data
            slide_count_in_data = presentation_data.count('"slide_number":')
            logger.info(f"   📊 Slide entries found in presentation_data: {slide_count_in_data}")
            if slide_count_in_data != len(presentation_manager.slides):
                logger.error(f"   ❌❌❌ MISMATCH: Expected {len(presentation_manager.slides)} slides but found {slide_count_in_data} entries in data!")
        logger.info(f"   📄 Instructions preview (last 500 chars): {instructions[-500:]}")
    
    await vendor_ws.send(config_json)
    logger.info("✅ Session configuration sent to OpenAI with tools")


async def relay_messages(client_ws: WebSocket, vendor_ws):
    """Relay messages between client and OpenAI WebSockets with format conversion."""
    
    # Track if we've received server.hello and sent session config
    session_configured = False
    
    async def client_to_vendor():
        """Relay messages from client to OpenAI, converting format."""
        try:
            while True:
                # Receive JSON from client
                data = await client_ws.receive_json()
                
                if data.get("type") == "audio":
                    # Convert our format to OpenAI format
                    audio_b64 = data.get("data")
                    if audio_b64:
                        openai_message = {
                            "type": "input_audio_buffer.append",
                            "audio": audio_b64
                        }
                        await vendor_ws.send(json.dumps(openai_message))
                        logger.debug(f"Sent audio chunk to OpenAI ({len(audio_b64)} chars)")
                
                elif data.get("type") == "audio_commit":
                    # Client signals end of audio input
                    commit_message = {
                        "type": "input_audio_buffer.commit"
                    }
                    await vendor_ws.send(json.dumps(commit_message))
                    logger.debug("Committed audio buffer to OpenAI")
                
                elif data.get("type") == "interrupt":
                    # Cancel current response
                    cancel_message = {
                        "type": "response.cancel"
                    }
                    await vendor_ws.send(json.dumps(cancel_message))
                    logger.info("Cancelled OpenAI response")
                
                elif data.get("type") == "start_presentation":
                    # Trigger AI to start presenting
                    logger.info("🚀 Starting presentation - updating session config and requesting response")
                    
                    # Verify presentation is loaded
                    if not presentation_manager.slides:
                        logger.error("❌ No presentation loaded! Cannot start presentation.")
                        await client_ws.send_json({
                            "type": "error",
                            "error": "No presentation loaded. Please upload a presentation first.",
                            "error_type": "no_presentation"
                        })
                        continue
                    
                    logger.info(f"   Presentation has {len(presentation_manager.slides)} slides")
                    first_slide = presentation_manager.slides[0]
                    logger.info(f"   First slide title: '{first_slide.get('title', 'N/A')}'")
                    logger.info(f"   First slide content preview: '{first_slide.get('content', '')[:200]}...'")
                    
                    # Note: We don't clear conversation here as OpenAI Realtime API manages it
                    # Instead, we rely on the session.update to provide fresh context
                    logger.info("   📝 Session will be updated with new presentation context")
                    
                    # CRITICAL: Update session config with NEW presentation context
                    # This ensures OpenAI has the latest presentation content in its instructions
                    logger.info("   🔄 Updating session config with presentation content...")
                    await send_session_config(vendor_ws)
                    logger.info("   ✅ Session config updated with NEW presentation content")
                    logger.info("   ⏳ Waiting for OpenAI to process session update...")
                    # Longer delay to ensure config is fully processed by OpenAI
                    await asyncio.sleep(1.5)
                    logger.info("   ✅ Proceeding with presentation start")
                    
                    # Add presentation data as conversation items (per OpenAI docs best practice)
                    # This ensures all slide data is in conversation context, not just instructions
                    logger.info("   📚 Adding presentation data as conversation items...")
                    await add_presentation_to_conversation(vendor_ws)
                    logger.info("   ✅ Presentation data added to conversation")
                    await asyncio.sleep(0.5)
                    
                    # Navigate to first slide
                    result = presentation_manager.navigate_to_slide("jump", 0)
                    slide_data = result.get("slide", {})
                    # Ensure slide_data has index field
                    if "index" not in slide_data:
                        slide_data["index"] = 0
                    
                    await client_ws.send_json({
                        "type": "slide_changed",
                        "slide_index": 0,
                        "total_slides": result.get("total_slides", 0),
                        "slide": slide_data,
                    })
                    logger.info(f"   📺 Initial slide set: index=0, title='{slide_data.get('title', 'N/A')}'")
                    
                    # Send start message - AI should use tools to get slide content
                    # Per OpenAI docs: Use tools to retrieve data, don't embed everything
                    start_message_text = {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Start presenting the presentation. Begin with slide 1."
                                }
                            ]
                        }
                    }
                    await vendor_ws.send(json.dumps(start_message_text))
                    logger.info("   🔄 Sent start message - AI will use tools to get slide content")
                    await asyncio.sleep(0.3)
                    
                    # Request a response
                    # Per OpenAI docs: Use tool_choice="required" only when tools are necessary
                    # For small presentations with content in conversation, "auto" is fine
                    total_slides = len(presentation_manager.slides)
                    if total_slides <= 5:
                        # Small presentation: Content in conversation, tools optional for navigation
                        start_message = {
                            "type": "response.create",
                            "response": {
                                "modalities": ["text", "audio"],
                                "tool_choice": "auto"  # Content in conversation, tools for navigation
                            }
                        }
                        logger.info("✅ Presentation start requested - content in conversation, tools optional")
                    else:
                        # Large presentation: Must use tools to get content
                        start_message = {
                            "type": "response.create",
                            "response": {
                                "modalities": ["text", "audio"],
                                "tool_choice": "required"  # Must use tools to retrieve content
                            }
                        }
                        logger.info("✅ Presentation start requested - AI must call tools to get content")
                    
                    await vendor_ws.send(json.dumps(start_message))
                
                elif data.get("type") == "navigate_slide":
                    # Manual slide navigation from user
                    action = data.get("action")
                    slide_index = data.get("slide_index")
                    logger.info(f"Manual slide navigation: {action}, slide_index: {slide_index}")
                    
                    # Navigate slide
                    result = presentation_manager.navigate_to_slide(action, slide_index)
                    
                    # Notify client of slide change
                    await client_ws.send_json({
                        "type": "slide_changed",
                        "slide_index": result.get("current_slide", 0),
                        "total_slides": result.get("total_slides", 0),
                        "slide": result.get("slide", {}),
                    })
                
                elif data.get("type") == "session.update":
                    # Forward session update directly
                    await vendor_ws.send(json.dumps(data))
                    logger.info("Forwarded session update to OpenAI")
                
                else:
                    # Forward other messages as-is
                    await vendor_ws.send(json.dumps(data))
                    logger.debug(f"Forwarded message to OpenAI: {data.get('type')}")
                    
        except WebSocketDisconnect:
            logger.info("Client WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error in client_to_vendor: {e}")
            traceback.print_exc()
            # Try to send error to client if still connected
            try:
                await client_ws.send_json({
                    "type": "error",
                    "error": f"Error processing client message: {str(e)}",
                    "error_type": "client_to_vendor_error"
                })
            except:
                pass  # Client may already be disconnected
    
    async def vendor_to_client():
        """Relay messages from OpenAI to client, converting format."""
        nonlocal session_configured
        # Track current response and whether it has function calls
        current_response_id = None
        current_response_has_function_call = False
        handled_call_ids = set()  # Track handled function call IDs to prevent duplicates
        try:
            while True:
                # Receive message from OpenAI (could be text or binary)
                message = await vendor_ws.recv()
                
                # Handle binary messages (shouldn't happen with OpenAI Realtime API, but be safe)
                if isinstance(message, bytes):
                    logger.warning("Received binary message from OpenAI, skipping")
                    continue
                
                # Parse JSON string
                try:
                    data = json.loads(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from OpenAI. Error: {e}")
                    logger.error(f"Message preview (first 500 chars): {message[:500]}")
                    # Send error to client
                    try:
                        await client_ws.send_json({
                            "type": "error",
                            "error": f"Invalid JSON from OpenAI: {str(e)}",
                            "error_type": "openai_json_error"
                        })
                    except:
                        pass
                    continue
                
                # Log the event type for debugging
                event_type = data.get("type")
                if event_type:
                    # Always log ALL events at INFO level for debugging
                    logger.info(f"📨 Received OpenAI event: {event_type}")
                    
                    # Log response-related events with more detail
                    if event_type.startswith("response."):
                        logger.info(f"   📢 Response event: {event_type}")
                        # Log response details for debugging
                        if "response" in data:
                            resp_data = data.get("response", {})
                            if isinstance(resp_data, dict):
                                logger.info(f"   Response keys: {list(resp_data.keys())}")
                                # Log status if available
                                if "status" in resp_data:
                                    logger.info(f"   Response status: {resp_data.get('status')}")
                                # Log output if available
                                if "output" in resp_data:
                                    output = resp_data.get("output", [])
                                    logger.info(f"   Response output items: {len(output)}")
                                    for idx, item in enumerate(output):
                                        logger.info(f"     Item {idx}: {item.get('type', 'unknown')}")
                    
                    # Log full event for audio-related events
                    if "audio" in event_type.lower():
                        logger.info(f"   🎵 Audio event - keys: {list(data.keys())}")
                        if "delta" in data:
                            delta_size = len(data.get("delta", ""))
                            logger.info(f"   Audio delta size: {delta_size} chars")
                        elif "audio" in data:
                            audio_size = len(str(data.get("audio", "")))
                            logger.info(f"   Audio data size: {audio_size} chars")
                        else:
                            logger.info(f"   No audio data found, all keys: {list(data.keys())}")
                    
                    # Log full data for response events to debug
                    if event_type.startswith("response."):
                        event_preview = json.dumps(data)[:800]
                        logger.info(f"   Full event data: {event_preview}")
                
                # Handle server.hello - send session config after receiving it
                if event_type == "server.hello" and not session_configured:
                    logger.info("Received server.hello, sending session config")
                    session_configured = True
                    # Only send config if presentation is loaded, otherwise wait for upload
                    if presentation_manager.slides:
                        logger.info("   ✅ Presentation already loaded, sending config with presentation content")
                        await send_session_config(vendor_ws)
                    else:
                        logger.info("   ⚠️ No presentation loaded yet - sending minimal config (will update when PPT uploaded)")
                        # Send minimal config without presentation data
                        minimal_config = {
                            "type": "session.update",
                            "session": {
                                "modalities": ["audio"],
                                "voice": "alloy",
                                "instructions": "You are a PowerPoint presentation assistant. Wait for the user to upload a presentation.",
                                "input_audio_format": "pcm16",
                                "output_audio_format": "pcm16",
                                "input_audio_transcription": {"model": "whisper-1"},
                                "turn_detection": {
                                    "type": "server_vad",
                                    "threshold": 0.5,
                                    "prefix_padding_ms": 300,
                                    "silence_duration_ms": 200,
                                    "interrupt_response": True,
                                },
                                "tools": TOOL_DEFINITIONS,
                                "tool_choice": "auto",  # AI decides when to use tools
                            }
                        }
                        await vendor_ws.send(json.dumps(minimal_config))
                        logger.info("   Minimal session config sent (no presentation data)")
                    # Forward server.hello to client
                    await client_ws.send_json({
                        "type": "server.hello",
                        "session": data.get("session", {})
                    })
                    continue
                
                # Convert OpenAI format to our client format
                if event_type == "response.audio.delta":
                    # Audio chunk from OpenAI
                    delta = data.get("delta", "")
                    if delta:
                        logger.info(f"🎵 Sending audio delta to client ({len(delta)} chars)")
                        await client_ws.send_json({
                            "type": "audio",
                            "data": delta
                        })
                    else:
                        logger.warning("Received response.audio.delta with empty delta")
                
                elif event_type == "response.output_item.added":
                    # Output item added (could be audio, text, or function_call)
                    item = data.get("item", {})
                    item_type = item.get("type")
                    logger.info(f"🎯 Output item added: {item_type}")
                    
                    if item_type == "function_call":
                        # Function call added - we'll handle it when done
                        function_name = item.get('name', 'unknown')
                        logger.info(f"   🔧 Function call ADDED: {function_name}")
                        logger.info(f"   📋 Function call details: {json.dumps(item, indent=2)[:500]}...")
                        # Track that this response has a function call
                        current_response_has_function_call = True
                    
                    if item_type == "audio":
                        # Audio item added - check all possible audio fields
                        audio_data = item.get("audio", "")
                        if not audio_data:
                            # Try other possible fields
                            audio_data = item.get("data", "")
                        if not audio_data:
                            # Check if it's in a nested structure
                            audio_obj = item.get("audio", {})
                            if isinstance(audio_obj, dict):
                                audio_data = audio_obj.get("data", "")
                        
                        if audio_data:
                            logger.info(f"🎵 Sending audio item to client ({len(audio_data)} chars)")
                            await client_ws.send_json({
                                "type": "audio",
                                "data": audio_data
                            })
                        else:
                            logger.warning(f"⚠️ Audio item has no audio data")
                    elif item_type == "text":
                        # Text item added
                        text = item.get("text", "")
                        if text:
                            # Check if AI is trying to output JSON instead of calling a tool
                            # This happens when AI outputs {"slide_number":3} instead of calling show_slide()
                            try:
                                parsed_json = json.loads(text.strip())
                                if isinstance(parsed_json, dict) and "slide_number" in parsed_json:
                                    slide_num = parsed_json["slide_number"]
                                    logger.warning(f"⚠️ AI output JSON instead of calling tool! Converting to show_slide({slide_num})")
                                    # Convert to tool call
                                    await handle_tool_call(vendor_ws, client_ws, {
                                        "name": "show_slide",
                                        "call_id": f"auto_{slide_num}",
                                        "arguments": json.dumps({"slide_number": slide_num})
                                    })
                                    # Don't forward the JSON text to client
                                    continue
                            except (json.JSONDecodeError, ValueError):
                                pass  # Not JSON, forward normally
                            
                            await client_ws.send_json({
                                "type": "text",
                                "text": text,
                                "role": "assistant"
                            })
                    else:
                        logger.debug(f"Output item type '{item_type}' not handled")
                
                elif event_type == "response.text.delta":
                    # Text delta from OpenAI
                    text_delta = data.get("delta", "")
                    # Check if this looks like JSON being streamed (e.g., {"slide_number":3})
                    # We'll accumulate and check in response.text.done
                    await client_ws.send_json({
                        "type": "text",
                        "text": text_delta,
                        "role": "assistant"
                    })
                
                elif event_type == "response.function_call_arguments.done":
                    # Function call arguments are complete - this is when we should execute the function call
                    # The item contains the function_call with complete arguments
                    item = data.get("item", {})
                    function_call = item.get("function_call", item)  # Try nested first, fallback to item itself
                    
                    function_name = function_call.get("name", "")
                    call_id = function_call.get("call_id", "")
                    arguments_str = function_call.get("arguments", "{}")
                    
                    if function_name and call_id:
                        # Check if we've already handled this call_id
                        if call_id in handled_call_ids:
                            logger.info(f"⏭️ Skipping already-handled function call: {function_name} (call_id: {call_id})")
                        else:
                            handled_call_ids.add(call_id)
                            logger.info(f"🔧🔧🔧 FUNCTION CALL ARGUMENTS COMPLETE 🔧🔧🔧")
                            logger.info(f"   Function: {function_name}")
                            logger.info(f"   Call ID: {call_id}")
                            logger.info(f"   Arguments: {arguments_str}")
                            
                            # Handle the function call
                            await handle_tool_call(vendor_ws, client_ws, {
                                "name": function_name,
                                "call_id": call_id,
                                "arguments": arguments_str
                            })
                    else:
                        logger.warning(f"⚠️ response.function_call_arguments.done missing function_name or call_id")
                        logger.warning(f"   Item structure: {json.dumps(item, indent=2)[:500]}")
                
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # User transcription
                    item = data.get("item", {})
                    transcript = item.get("transcript", "")
                    if transcript:
                        await client_ws.send_json({
                            "type": "text",
                            "text": transcript,
                            "role": "user"
                        })
                        logger.info(f"User transcript: {transcript}")
                
                elif event_type == "conversation.item.created":
                    # Handle conversation items (transcripts, function calls, etc.)
                    item = data.get("item", {})
                    item_type = item.get("type")
                    
                    if item_type == "input_audio_transcription":
                        transcript = item.get("transcript", "")
                        if transcript:
                            await client_ws.send_json({
                                "type": "text",
                                "text": transcript,
                                "role": "user"
                            })
                            logger.info(f"📝 User transcript: {transcript}")
                            
                            # Note: Navigation is handled via tools (show_slide, navigate_slide)
                            # The AI will detect navigation requests and call the appropriate tool
                            # No manual interception needed - let tools handle it
                            
                            # Log question detection for monitoring (no fallback action)
                            question_indicators = ["what", "tell me", "explain", "how", "why", "which", "where", "when", "who", "dive", "more", "about", "investors", "features", "pricing", "team"]
                            is_question = any(indicator in transcript_lower for indicator in question_indicators) or transcript.strip().endswith("?")
                            
                            if is_question and presentation_manager.slides:
                                logger.info(f"   🔍 Question detected: '{transcript}'")
                                logger.info(f"   ℹ️ Expecting: search_slides() → show_slide() → answer (per ReAct pattern)")
                    elif item_type == "function_call":
                        # Handle function calls created in conversation
                        # Note: This might be redundant if response.function_call_arguments.done already handled it
                        function_name = item.get('name', 'unknown')
                        call_id = item.get('call_id', '')
                        
                        if call_id and call_id in handled_call_ids:
                            logger.info(f"⏭️ Skipping already-handled function call in conversation.item.created: {function_name} (call_id: {call_id})")
                        else:
                            if call_id:
                                handled_call_ids.add(call_id)
                            logger.info(f"🔧 Function call detected in conversation.item.created: {function_name}")
                            logger.info(f"   📋 Function call details: {json.dumps(item, indent=2)[:500]}...")
                            # Track that this response has a function call
                            current_response_has_function_call = True
                            await handle_tool_call(vendor_ws, client_ws, item)
                
                elif event_type == "response.text.done":
                    # Handle completed text output - check if AI output JSON instead of calling tools
                    text = data.get("text", "")
                    if text:
                        logger.info(f"📝 Text output completed: {text[:200]}...")
                        # CRITICAL: Check if AI is outputting JSON instead of calling tools
                        # This happens when AI outputs {"slide_number":3} instead of calling show_slide()
                        try:
                            parsed_json = json.loads(text.strip())
                            if isinstance(parsed_json, dict) and "slide_number" in parsed_json:
                                slide_num = parsed_json["slide_number"]
                                logger.warning(f"⚠️⚠️⚠️ AI OUTPUT JSON INSTEAD OF CALLING TOOL!")
                                logger.warning(f"   Text: {text}")
                                logger.warning(f"   Converting to show_slide({slide_num})")
                                # Convert to tool call
                                await handle_tool_call(vendor_ws, client_ws, {
                                    "name": "show_slide",
                                    "call_id": f"auto_{slide_num}_{int(time.time())}",
                                    "arguments": json.dumps({"slide_number": slide_num})
                                })
                                # Don't forward the JSON text to client
                                continue
                        except (json.JSONDecodeError, ValueError):
                            pass  # Not JSON, forward normally
                
                elif event_type == "response.output_item.done":
                    # Handle completed output items (including function calls)
                    item = data.get("item", {})
                    item_type = item.get("type")
                    
                    if item_type == "function_call":
                        # Handle tool/function call
                        # Note: This might be redundant if response.function_call_arguments.done already handled it
                        function_name = item.get('name', 'unknown')
                        call_id = item.get('call_id', '')
                        
                        if call_id and call_id in handled_call_ids:
                            logger.info(f"⏭️ Skipping already-handled function call in response.output_item.done: {function_name} (call_id: {call_id})")
                        else:
                            if call_id:
                                handled_call_ids.add(call_id)
                            logger.info(f"🔧 Function call detected in response.output_item.done: {function_name}")
                            logger.info(f"   📋 Function call details: {json.dumps(item, indent=2)[:500]}...")
                            # Track that this response has a function call
                            current_response_has_function_call = True
                            await handle_tool_call(vendor_ws, client_ws, item)
                    elif item_type == "audio":
                        # Handle audio output items
                        audio_data = item.get("audio", "")
                        if audio_data:
                            logger.info(f"🎵 Sending audio item to client ({len(audio_data)} chars)")
                            await client_ws.send_json({
                                "type": "audio",
                                "data": audio_data
                            })
                    elif item_type == "text":
                        # Handle text output items
                        text = item.get("text", "")
                        if text:
                            # CRITICAL: Check if AI is outputting JSON instead of calling tools
                            # This happens when AI outputs {"slide_number":3} instead of calling show_slide()
                            try:
                                parsed_json = json.loads(text.strip())
                                if isinstance(parsed_json, dict) and "slide_number" in parsed_json:
                                    slide_num = parsed_json["slide_number"]
                                    logger.warning(f"⚠️⚠️⚠️ AI OUTPUT JSON INSTEAD OF CALLING TOOL!")
                                    logger.warning(f"   Text: {text}")
                                    logger.warning(f"   Converting to show_slide({slide_num})")
                                    # Convert to tool call
                                    await handle_tool_call(vendor_ws, client_ws, {
                                        "name": "show_slide",
                                        "call_id": f"auto_{slide_num}_{int(time.time())}",
                                        "arguments": json.dumps({"slide_number": slide_num})
                                    })
                                    # Don't forward the JSON text to client
                                    continue
                            except (json.JSONDecodeError, ValueError):
                                pass  # Not JSON, forward normally
                            
                            await client_ws.send_json({
                                "type": "text",
                                "text": text,
                                "role": "assistant"
                            })
                
                elif event_type == "response.created":
                    # Response object was created
                    logger.info("Response created - checking status")
                    response_obj = data.get("response", {})
                    if isinstance(response_obj, dict):
                        response_id = response_obj.get("id")
                        response_status = response_obj.get("status")
                        logger.info(f"Response ID: {response_id}, Status: {response_status}")
                        # Log all response fields
                        logger.info(f"Response fields: {list(response_obj.keys())}")
                    # Forward to client
                    await client_ws.send_json({"type": "response.created"})
                
                elif event_type == "response.started":
                    await client_ws.send_json({"type": "response.started"})
                    logger.info("Response started - expecting audio/text deltas")
                    # Log response details and track response
                    response_id = data.get("response", {}).get("id") if isinstance(data.get("response"), dict) else None
                    if response_id:
                        logger.info(f"Response ID: {response_id}")
                        current_response_id = response_id
                        current_response_has_function_call = False  # Reset tracking
                
                elif event_type == "response.done":
                    await client_ws.send_json({"type": "response.done"})
                    logger.info("✅ Response done")
                    # Log response details to see why no audio
                    response_obj = data.get("response", {})
                    if isinstance(response_obj, dict):
                        response_status = response_obj.get("status")
                        output_items = response_obj.get("output", [])
                        logger.info(f"   Response status: {response_status}")
                        logger.info(f"   Response keys: {list(response_obj.keys())}")
                        logger.info(f"   Output items count: {len(output_items) if output_items else 0}")
                        # Check if response includes function calls
                        has_function_call = False
                        if output_items:
                            for idx, item in enumerate(output_items):
                                item_type = item.get("type")
                                logger.info(f"   Output item {idx}: type={item_type}, keys={list(item.keys())}")
                                if item_type == "function_call":
                                    has_function_call = True
                                    logger.info(f"   ✅ Found function_call in output item {idx}")
                                # Check if audio is in the output items
                                if item_type == "audio":
                                    audio_data = item.get("audio", "")
                                    if audio_data:
                                        logger.info(f"   🎵 Found audio in output item {idx} ({len(audio_data)} chars)")
                                        # Send it to client!
                                        await client_ws.send_json({
                                            "type": "audio",
                                            "data": audio_data
                                        })
                                    else:
                                        logger.warning(f"   ⚠️ Audio item {idx} has no audio data")
                        else:
                            logger.warning("   ⚠️ No output items in response.done - response may have failed")
                        
                        # Check if this response had any function calls (check both tracking methods)
                        response_has_tool_call = has_function_call or current_response_has_function_call
                        
                        # Log if no function calls were made (for monitoring/debugging)
                        if not response_has_tool_call and output_items:
                            logger.warning("   ⚠️ Response completed WITHOUT function calls!")
                            logger.warning("   ⚠️ tool_choice is 'required' but OpenAI didn't call a tool")
                            logger.info("   ℹ️ Output items types: " + ", ".join([item.get("type", "unknown") for item in output_items]))
                            # Note: With tool_choice="required", OpenAI should always call a tool.
                            # If it didn't, we just log it rather than auto-inject (which caused loops).
                            # Reset tracking for next response
                            current_response_id = None
                            current_response_has_function_call = False
                        else:
                            # Reset tracking for next response
                            current_response_id = None
                            current_response_has_function_call = False
                    # Also log full event for debugging
                    logger.debug(f"   Full response.done event: {json.dumps(data)[:500]}")
                
                elif event_type == "response.interrupted":
                    await client_ws.send_json({"type": "interrupted"})
                    logger.info("🛑 Response interrupted by user")
                
                elif event_type == "input_audio_buffer.speech_started":
                    await client_ws.send_json({"type": "speech_started"})
                    logger.info("User started speaking - this will interrupt assistant if speaking")
                
                elif event_type == "input_audio_buffer.speech_stopped":
                    await client_ws.send_json({"type": "speech_stopped"})
                    logger.info("User stopped speaking - OpenAI should trigger response automatically")
                
                elif event_type == "input_audio_buffer.committed":
                    logger.info("Input audio buffer committed")
                    await client_ws.send_json({"type": "input_audio_buffer.committed"})
                
                elif event_type == "output_audio_buffer.started":
                    logger.info("🎵 Output audio buffer started - audio streaming beginning")
                    await client_ws.send_json({"type": "output_audio_buffer.started"})
                
                elif event_type == "output_audio_buffer.speech_started":
                    logger.info("🎵 Assistant started speaking (audio output)")
                    await client_ws.send_json({"type": "output_audio_buffer.speech_started"})
                
                elif event_type == "output_audio_buffer.speech_stopped":
                    logger.info("🎵 Assistant stopped speaking (audio output)")
                    await client_ws.send_json({"type": "output_audio_buffer.speech_stopped"})
                
                elif event_type == "output_audio_buffer.interrupted":
                    logger.info("🛑 Output audio buffer interrupted - user spoke during assistant response")
                    await client_ws.send_json({"type": "interrupted"})
                
                elif event_type == "error":
                    await client_ws.send_json({
                        "type": "error",
                        "error": str(data)
                    })
                    logger.error(f"OpenAI Error: {data}")
                
                elif event_type == "session.created":
                    logger.info("OpenAI session created")
                    # Optionally send confirmation to client
                    await client_ws.send_json({"type": "session.created"})
                
                else:
                    # Forward unknown events as-is (for debugging)
                    logger.info(f"Received unknown/unhandled event: {event_type}")
                    # Log full data for debugging (truncated)
                    event_preview = json.dumps(data)[:500]
                    logger.info(f"Event data preview: {event_preview}")
                    # Still forward to client in case frontend can handle it
                    await client_ws.send_json(data)
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"OpenAI WebSocket disconnected: {e}")
            # Notify client of OpenAI disconnection
            try:
                await client_ws.send_json({
                    "type": "error",
                    "error": "OpenAI connection closed",
                    "error_type": "openai_disconnected"
                })
            except:
                pass  # Client may already be disconnected
        except Exception as e:
            logger.error(f"Error in vendor_to_client: {e}")
            traceback.print_exc()
            # Try to send error to client if still connected
            try:
                await client_ws.send_json({
                    "type": "error",
                    "error": f"Error processing OpenAI message: {str(e)}",
                    "error_type": "vendor_to_client_error"
                })
            except:
                pass  # Client may already be disconnected
    
    # Run both relay tasks concurrently
    # vendor_to_client will handle server.hello and send session config
    tasks = [
        asyncio.create_task(client_to_vendor()),
        asyncio.create_task(vendor_to_client()),
    ]
    
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED
    )
    
    # Cancel remaining tasks
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error cancelling task: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections from clients."""
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"Client connected: {client_ip}")
    
    await websocket.accept()
    
    if not OPENAI_API_KEY:
        error_msg = "OPENAI_API_KEY not set"
        logger.error(error_msg)
        await send_error_safe(websocket, "config_error", error_msg)
        await websocket.close(code=1008, reason=error_msg)
        return
    
    try:
        # Connect to OpenAI Realtime API
        async with websockets.connect(
            OPENAI_REALTIME_URL,
            extra_headers=get_openai_headers(),
        ) as vendor_ws:
            logger.info("Connected to OpenAI Realtime API")
            
            # Start bidirectional relay (session config sent after server.hello)
            await relay_messages(websocket, vendor_ws)
            
    except websockets.exceptions.InvalidHandshake as e:
        error_msg = f"OpenAI WebSocket handshake failed: {e}"
        logger.error(error_msg)
        await send_error_safe(websocket, "handshake_error", error_msg)
        await websocket.close(code=1011)
        
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {client_ip}")
        
    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(error_msg)
        traceback.print_exc()
        try:
            await send_error_safe(websocket, "unexpected_error", error_msg)
        except:
            pass
        try:
            await websocket.close()
        except:
            pass


@app.post("/api/upload-presentation")
async def upload_presentation(file: UploadFile = File(...)):
    """Upload a PowerPoint presentation file."""
    try:
        if not file.filename.endswith(('.pptx', '.ppt')):
            raise HTTPException(status_code=400, detail="Only .pptx and .ppt files are supported")
        
        # Read file content
        contents = await file.read()
        
        # Load presentation
        result = presentation_manager.load_presentation(contents)
        
        if result.get("success"):
            logger.info(f"✅ Presentation uploaded: {file.filename}, {result['total_slides']} slides")
            # Log first slide to verify content
            if result["slides"] and len(result["slides"]) > 0:
                first_slide = result["slides"][0]
                logger.info(f"   First slide title: {first_slide.get('title', 'N/A')}")
                logger.info(f"   First slide content preview: {first_slide.get('content', '')[:200]}...")
            
            # Note: Session config will be updated when frontend sends start_presentation message
            # or when next server.hello is received. This ensures AI has slide data.
            logger.info(f"   ℹ️ Session configs will be updated when clients trigger start_presentation")
            
            return {
                "success": True,
                "filename": file.filename,
                "total_slides": result["total_slides"],
                "slides": result["slides"],
            }
        else:
            raise HTTPException(status_code=400, detail=f"Failed to load presentation: {result.get('error')}")
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading presentation: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing presentation: {str(e)}")
