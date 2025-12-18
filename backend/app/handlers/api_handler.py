"""API handlers for HTTP endpoints."""
import logging
from fastapi import UploadFile, File, HTTPException
from app.presentation import presentation_manager

logger = logging.getLogger(__name__)


class APIHandler:
    """Handles HTTP API endpoints."""
    
    def __init__(self, presentation_manager):
        """Initialize API handler."""
        self.presentation_manager = presentation_manager
    
    async def upload_presentation(self, file: UploadFile) -> dict:
        """Upload a PowerPoint presentation file.
        
        Args:
            file: Uploaded file
            
        Returns:
            Upload result with slide information
            
        Raises:
            HTTPException: If upload fails
        """
        if not file.filename.endswith(('.pptx', '.ppt')):
            raise HTTPException(
                status_code=400, 
                detail="Only .pptx and .ppt files are supported"
            )
        
        try:
            contents = await file.read()
            result = self.presentation_manager.load_presentation(contents)
            
            if result.get("success"):
                logger.info(f"Presentation uploaded: {file.filename}, {result['total_slides']} slides")
                return {
                    "success": True,
                    "filename": file.filename,
                    "total_slides": result["total_slides"],
                    "slides": result["slides"],
                }
            else:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Failed to load presentation: {result.get('error')}"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error uploading presentation: {e}")
            raise HTTPException(
                status_code=500, 
                detail=f"Error processing presentation: {str(e)}"
            )

