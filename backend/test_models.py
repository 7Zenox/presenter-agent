"""Test script to check available Gemini models."""
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY not set")
    exit(1)

client = genai.Client(api_key=api_key)

print("Testing model availability...\n")

# Try to list models
try:
    models = list(client.models.list())
    print(f"Found {len(models)} models:")
    for model in models:
        print(f"  - {model.name}")
    print()
except Exception as e:
    print(f"Error listing models: {e}\n")

# Test specific models
test_models = ["gemini-pro", "gemini-1.5-flash", "gemini-1.5-pro"]

for model_name in test_models:
    print(f"Testing {model_name}...")
    try:
        response = client.models.generate_content(
            model=model_name,
            contents="Say hello"
        )
        print(f"  ✓ {model_name} works! Response: {response.text[:50]}...")
    except Exception as e:
        error_str = str(e)
        if "404" in error_str or "NOT_FOUND" in error_str:
            print(f"  ✗ {model_name} not found (404)")
        elif "429" in error_str or "quota" in error_str.lower():
            print(f"  ✗ {model_name} quota exceeded (429)")
        else:
            print(f"  ✗ {model_name} error: {error_str[:100]}")



