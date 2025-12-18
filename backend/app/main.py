"""Main FastAPI application entry point."""
import logging
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.presentation import presentation_manager
from app.handlers.websocket_handler import WebSocketHandler
from app.handlers.api_handler import APIHandler
from app.utils.errors import send_error_safe

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Presenter Agent API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize handlers
websocket_handler = WebSocketHandler()
api_handler = APIHandler(presentation_manager)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connections from clients."""
    client_ip = websocket.client.host if websocket.client else "unknown"
    logger.info(f"Client connected: {client_ip}")
    
    await websocket.accept()
    
    if not settings.validate():
        error_msg = "OPENAI_API_KEY not set"
        logger.error(error_msg)
        await send_error_safe(websocket, "config_error", error_msg)
        await websocket.close(code=1008, reason=error_msg)
        return
    
    try:
        # Connect to OpenAI Realtime API
        async with websockets.connect(
            settings.OPENAI_REALTIME_URL,
            extra_headers=settings.get_openai_headers(),
        ) as vendor_ws:
            logger.info("Connected to OpenAI Realtime API")
            
            # Start bidirectional relay
            await websocket_handler.relay_messages(websocket, vendor_ws)
            
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
    return await api_handler.upload_presentation(file)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

