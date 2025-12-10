# Import and expose the FastAPI app from the app package
from app.main import app

# Expose app at module level for FastAPI CLI
__all__ = ["app"]
