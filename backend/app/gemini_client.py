"""Gemini API client helper with model listing."""
import os
from dotenv import load_dotenv
from google import genai
from typing import List, Dict

load_dotenv()


def get_client():
    """Get a configured Gemini client."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable not set")
    return genai.Client(api_key=api_key)


def list_available_models() -> List[Dict]:
    """List all available Gemini models."""
    try:
        client = get_client()
        models = client.models.list()
        
        available_models = []
        for model in models:
            available_models.append({
                "name": model.name,
                "display_name": getattr(model, "display_name", ""),
                "description": getattr(model, "description", ""),
                "supported_methods": getattr(model, "supported_generation_methods", [])
            })
        
        return available_models
    except Exception as e:
        print(f"Error listing models: {e}")
        return []


def get_model_for_generate_content() -> str:
    """
    Get the best available model for generate_content.
    Uses actual available models from the API.
    """
    client = get_client()
    
    # Default models to try (in order of preference)
    default_models = [
        "gemini-2.5-flash",        # Latest stable flash model
        "gemini-2.0-flash-lite",   # Lightweight 2.0 model
        "gemini-2.0-flash",        # Standard 2.0 flash
        "gemini-flash-latest",      # Latest flash
        "gemini-pro-latest",        # Latest pro
    ]
    
    try:
        # Try to verify the model exists by listing models
        models_iter = client.models.list()
        models = list(models_iter)
        
        if not models:
            print(f"Warning: No models returned from API, using default: {default_models[0]}")
            return default_models[0]
        
        available_model_names = [m.name for m in models]
        # Strip 'models/' prefix if present for comparison
        available_models_clean = [m.replace("models/", "") for m in available_model_names]
        print(f"Available models from API: {available_model_names}")
        
        # Preferred models in order (matching what's actually available)
        preferred_models = [
            "gemini-2.5-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
            "gemini-flash-latest",
            "gemini-pro-latest",
            "gemini-2.5-pro",
        ]
        
        # Try preferred models first
        for preferred in preferred_models:
            # Check both with and without models/ prefix
            if preferred in available_models_clean or f"models/{preferred}" in available_model_names:
                model_name = preferred if preferred in available_models_clean else preferred
                print(f"Selected model: {model_name}")
                return model_name
        
        # Last resort: return first available model that supports generate_content
        for model in models:
            model_name = model.name.replace("models/", "") if model.name.startswith("models/") else model.name
            if hasattr(model, "supported_generation_methods"):
                methods = model.supported_generation_methods
                if "generateContent" in methods or "GENERATE_CONTENT" in methods:
                    print(f"Selected model (fallback): {model_name}")
                    return model_name
        
        # If we can't find any, return first default
        print(f"Warning: No suitable model found in list, defaulting to {default_models[0]}")
        return default_models[0]
        
    except Exception as e:
        print(f"Warning: Could not list models ({type(e).__name__}: {e}), defaulting to {default_models[0]}")
        return default_models[0]


if __name__ == "__main__":
    """Print available models when run directly."""
    print("Available Gemini Models:\n")
    models = list_available_models()
    for model in models:
        print(f"Name: {model['name']}")
        print(f"  Display Name: {model['display_name']}")
        print(f"  Description: {model['description']}")
        print(f"  Supported Methods: {model['supported_methods']}")
        print()

