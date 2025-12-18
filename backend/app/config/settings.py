"""Application settings and configuration."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application configuration settings."""
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_REALTIME_URL: str = os.getenv(
        "OPENAI_REALTIME_URL",
        "wss://api.openai.com/v1/realtime?model=gpt-realtime"
    )
    
    # API Configuration
    API_HOST: str = os.getenv("API_HOST", "localhost")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    
    @classmethod
    def get_openai_headers(cls) -> dict:
        """Get headers for OpenAI WebSocket connection."""
        return {
            "Authorization": f"Bearer {cls.OPENAI_API_KEY}",
            "openai-beta": "realtime=v1",
        }
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that required settings are present."""
        if not cls.OPENAI_API_KEY:
            return False
        return True


# Global settings instance
settings = Settings()

