"""Error handling utilities."""
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


async def send_error_safe(ws: WebSocket, error_type: str, error_message: str) -> None:
    """Safely send error messages to the client WebSocket as JSON.
    
    Args:
        ws: WebSocket connection
        error_type: Type of error
        error_message: Error message to send
    """
    try:
        await ws.send_json({
            "type": "error",
            "error": error_message,
            "error_type": error_type
        })
    except Exception as e:
        logger.error(f"Error sending error message to client: {e}")

