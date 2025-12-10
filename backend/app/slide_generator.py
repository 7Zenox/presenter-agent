"""Slide generation using Gemini text model."""
from typing import List
from app.models import Slide
from app.gemini_client import get_client, get_model_for_generate_content


def generate_slides(topic: str) -> List[Slide]:
    """Generate slides for a given topic using Gemini."""
    client = get_client()
    model_name = get_model_for_generate_content()
    
    prompt = f"""Generate a presentation outline with 5-6 slides on the topic: "{topic}"

Return the response as a JSON array with this exact structure:
[
  {{
    "id": 1,
    "title": "Slide Title",
    "bullets": ["Bullet point 1", "Bullet point 2", "Bullet point 3"]
  }},
  ...
]

Each slide should have:
- A clear, concise title
- 3-5 bullet points covering key concepts
- Logical flow from one slide to the next

Return ONLY the JSON array, no markdown formatting or additional text."""

    # Fallback models if primary fails (free-tier first)
    fallback_models = [
        "gemini-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]
    
    models_to_try = [model_name] + [m for m in fallback_models if m != model_name]
    
    for attempt_model in models_to_try:
        try:
            response = client.models.generate_content(
                model=attempt_model,
                contents=prompt
            )
            text = response.text.strip()
            
            # Remove markdown code blocks if present
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            
            import json
            slides_data = json.loads(text)
            
            slides = []
            for slide_data in slides_data:
                slide = Slide(
                    id=slide_data["id"],
                    title=slide_data["title"],
                    bullets=slide_data.get("bullets", [])
                )
                slides.append(slide)
            
            print(f"Successfully generated slides using model: {attempt_model}")
            return slides
        
        except Exception as e:
            error_str = str(e)
            # Check if it's a quota/rate limit error
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                print(f"Quota exceeded for {attempt_model}, trying next model...")
                if attempt_model == models_to_try[-1]:
                    # Last model failed, raise the error
                    raise Exception(f"Failed to generate slides: All models exhausted quota. Error: {e}")
                continue
            else:
                # Other error, try next model
                if attempt_model == models_to_try[-1]:
                    raise Exception(f"Failed to generate slides: {e}")
                continue
    
    raise Exception("Failed to generate slides: No models available")

