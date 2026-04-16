import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def list_models():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY not found.")
        return

    client = genai.Client(api_key=api_key)
    
    print("Fetching available models...")
    with open("available_models.txt", "w", encoding="utf-8") as f:
        f.write("Available Gemini Models:\n")
        f.write("=" * 30 + "\n")
        for model in client.models.list():
            line = f"Name: {model.name}\nID: {model.name.split('/')[-1]}\nSupported Actions: {model.supported_actions}\n{'-' * 30}\n"
            f.write(line)
            print(f"Found: {model.name}")

if __name__ == "__main__":
    list_models()
    print("\nModel list saved to available_models.txt")
