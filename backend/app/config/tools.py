"""Tool definitions for OpenAI Realtime API."""
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

