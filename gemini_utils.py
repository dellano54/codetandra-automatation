import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
import asyncio
import base64
import re

load_dotenv()

def get_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY not found in environment variables. Please add it to your .env file.")
    return genai.Client(api_key=api_key)

async def call_gemini_with_retry(prompt, images=None, screenshot_bytes=None, max_retries=5):
    client = get_client()
    # Reverting to Gemma as requested
    model_id = 'gemma-4-26b-a4b-it'
    contents = [prompt]
    
    if screenshot_bytes:
        contents.append(types.Part.from_bytes(data=screenshot_bytes, mime_type='image/png'))
    if images:
        for img_data in images[:3]:
            if img_data.startswith('data:image'):
                try:
                    header, encoded = img_data.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1]
                    data = base64.b64decode(encoded)
                    if len(data) > 100:
                        contents.append(types.Part.from_bytes(data=data, mime_type=mime_type))
                except: pass

    # Gemma models often support thinking
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(include_thoughts=True)
    )

    for attempt in range(max_retries):
        current_timeout = 60 + (attempt * 30)
        try:
            print(f"    [AI] Generating response with {model_id} (Attempt {attempt + 1})...", flush=True)
            response = await asyncio.wait_for(
                asyncio.to_thread(client.models.generate_content, model=model_id, contents=contents, config=config),
                timeout=current_timeout
            )
            if response and response.text:
                return response.text
        except Exception as e:
            error_str = str(e).lower()
            print(f"    [WARN] Attempt {attempt+1} failed: {e}", flush=True)
            if "quota" in error_str or "429" in error_str:
                await asyncio.sleep(30 * (attempt + 1))
            else:
                await asyncio.sleep(5)
    return ""

async def analyze_mcq(question_text, options, images=None, screenshot=None, failed_combinations=None, is_multiple=False):
    options_str = "\n".join([f"{opt['letter']}. {opt['text']}" for opt in options])
    retry_context = f"\nDO NOT select: {'; '.join([', '.join(c) for c in failed_combinations])}" if failed_combinations else ""
    type_instr = "Select all correct letters (e.g., 'A, C')" if is_multiple else "Provide ONLY the correct option letter (A, B, C, or D)."

    prompt = f"Expert DBMS analysis.\n{type_instr}{retry_context}\nQuestion:\n{question_text}\nOptions:\n{options_str}\nReturn ONLY the letter(s)."
    
    answer_text = await call_gemini_with_retry(prompt, images=images, screenshot_bytes=screenshot)
    found_letters = sorted(list(set(re.findall(r'\b([A-D])\b', answer_text.upper()))))
    return found_letters

async def analyze_coding(problem_statement, current_code, test_cases="", error_message="", images=None, screenshot=None):
    error_context = f"\nPREVIOUS ERROR:\n{error_message}" if error_message else ""
    prompt = f"Expert SQL developer.\n{error_context}\nProblem:\n{problem_statement}\nCurrent:\n{current_code}\nReturn ONLY the COMPLETE code without markdown."
    
    code = await call_gemini_with_retry(prompt, images=images, screenshot_bytes=screenshot)
    code = (code or "").strip()
    if code.startswith("```"):
        lines = code.split("\n")
        if lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].startswith("```"): lines = lines[:-1]
        code = "\n".join(lines).strip()
    return code
