import asyncio
import os
import json
import getpass
import re
import datetime
import sys
from playwright.async_api import async_playwright

# Fix Windows console encoding for Unicode characters
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
from extraction_funcs import (
    extract_mcq_content,
    extract_coding_content,
    wait_for_question_load,
    format_mcq_output,
    format_coding_output
)

CREDENTIALS_FILE = "credentials.json"
USER_DATA_DIR = "playwright-user-data"
COURSE_URL = "https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295"
CACHE_FILE = "memory/question_cache.json"

def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    return None

def save_credentials(email, password):
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump({"email": email, "password": password}, f)

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_cache(cache):
    os.makedirs("memory", exist_ok=True)
    with open(CACHE_FILE, "w", encoding='utf-8') as f:
        json.dump(cache, f, indent=2)

async def login_if_needed(page, credentials):
    print("Navigating to login page...")
    try:
        await page.goto("https://srmeaswari.codetantra.com/login.jsp", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"Initial navigation failed ({e}), retrying once...")
        await asyncio.sleep(2)
        await page.goto("https://srmeaswari.codetantra.com/login.jsp", wait_until="domcontentloaded", timeout=30000)

    if "home.jsp" in page.url:
        print("Already logged in via session.")
        return True

    if not credentials:
        print("\nNo credentials found. Please enter them.")
        email = input("Email: ")
        password = getpass.getpass("Password: ")
        save_credentials(email, password)
        credentials = {"email": email, "password": password}

    print(f"Logging in as {credentials['email']}...")
    await page.wait_for_selector("#loginEmail", timeout=10000)
    await page.fill("#loginEmail", credentials["email"])
    await page.fill("#loginPassword", credentials["password"])

    await page.evaluate("""() => {
        const btn = document.getElementById('loginBtn');
        if (btn) {
            btn.classList.remove('disabled');
            btn.removeAttribute('disabled');
        }
    }""")

    await page.click("#loginBtn")

    try:
        await page.wait_for_url("**/home.jsp", timeout=15000)
        print("Login successful!")
        return True
    except Exception:
        print("Login redirection failed. Please check your credentials.")
        return False

async def fetch_course_contents(page):
    """Fetch the full course structure and IDs via the REST API"""
    print("Fetching course contents structure...")
    try:
        euc_id = COURSE_URL.split('eucId=')[1].split('&')[0]
        api_url = f"https://srmeaswari.codetantra.com/secure/rest/a2/euc/gecc?eucId={euc_id}"

        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const response = await fetch('{api_url}');
                    if (!response.ok) return {{ error: 'API failed: ' + response.status }};
                    return await response.json();
                }} catch (e) {{
                    return {{ error: 'Fetch failed: ' + e.message }};
                }}
            }}
        """)

        if result and result.get('result') == 0:
            return result.get('data', {})
        else:
            print(f"  [WARN] Failed to fetch contents: {result.get('error') or result.get('msg')}")
            return None
    except Exception as e:
        print(f"  [ERROR] Error fetching contents: {e}")
        return None

async def scan_sidebar_for_unfinished(page, frame):
    """Scan sidebar, update cache with links and status, return incomplete questions list"""
    # 1. Fetch course structure to get links
    course_data = await fetch_course_contents(page)
    question_links = {}
    if course_data:
        print("Processing course structure to generate direct links...")
        euc_id = course_data.get('id')
        # Correct hash format: #/eucs/[EUC_ID]/contents/[UNIT_ID]/[LESSON_ID]/[QUESTION_ID]
        base_url = f"https://srmeaswari.codetantra.com/secure/course.jsp?eucId={euc_id}#/eucs/{euc_id}/contents"
        for unit in course_data.get('contents', []):
            u_id = unit.get('id')
            for lesson in unit.get('contents', []):
                l_id = lesson.get('id')
                for item in lesson.get('contents', []):
                    if item.get('type') == 'question':
                        q_id = item.get('id')
                        if u_id and l_id and q_id:
                            question_links[item.get('name', '')] = f"{base_url}/{u_id}/{l_id}/{q_id}"

    # 2. Expand all units
    print("Expanding sidebar units...")
    await page.evaluate("""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe || !iframe.contentDocument) return;
        const buttons = iframe.contentDocument.querySelectorAll('button');
        for (const btn of buttons) {
            const text = btn.textContent || '';
            if (text.includes('Unit') && !text.includes('.') && btn.getAttribute('aria-expanded') !== 'true') {
                btn.click();
            }
        }
    }""")
    await asyncio.sleep(2)

    # 3. Scan for status
    print("Scanning sidebar for question status...")
    questions = await frame.locator('button').evaluate_all(r"""
        (buttons) => {
            const results = [];
            for (const btn of buttons) {
                const text = btn.textContent?.trim() || '';
                const title = btn.getAttribute('title') || '';
                if (/^\d+\.\d+\.\d+\./.test(text) || /^\d+\.\d+\.\d+\./.test(title) || text.includes('Exercise') || title.includes('Exercise')) {
                    const svg = btn.querySelector('svg');
                    let status = 'not_started';
                    if (svg) {
                        const cls = (svg.className?.baseVal || svg.className || '').toString();
                        if (cls.includes('text-success')) status = 'completed';
                        else if (cls.includes('text-accent')) status = 'in_progress';
                    }
                    results.push({ text, title, status });
                }
            }
            return results;
        }
    """)

    # 4. Update JSON Cache
    cache = load_cache()
    for q in questions:
        q_name = q['title'] or q['text']
        link = question_links.get(q_name)
        if not link:
            # Try fuzzy match (remove numbers)
            clean_name = re.sub(r'^\d+\.\d+\.\d+\.\s*', '', q_name)
            for name, l in question_links.items():
                if clean_name in name or name in clean_name:
                    link = l
                    break

        cache[q_name] = {
            "link": link,
            "status": q['status'],
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    save_cache(cache)

    # 5. Sort and return incomplete questions
    def sort_key(q):
        m = re.match(r'(\d+)\.(\d+)\.(\d+)', q['text'])
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (999,999,999)

    incomplete = sorted([q for q in questions if q['status'] != 'completed'], key=sort_key)

    # Add links to incomplete questions
    for q in incomplete:
        q_name = q['title'] or q['text']
        q['link'] = cache.get(q_name, {}).get('link')

    print(f"\n{'='*60}")
    print(f"INCOMPLETE QUESTIONS ({len(incomplete)} total):")
    print('='*60)
    for i, q in enumerate(incomplete[:10], 1):
        status_char = 'I' if q['status'] == 'in_progress' else 'N'
        link_short = 'OK' if cache.get(q['title'] or q['text'], {}).get('link') else 'NO LINK'
        print(f"{i:2}. [{status_char}] {q['text'][:55]}... ({link_short})")
    if len(incomplete) > 10:
        print(f"    ... and {len(incomplete) - 10} more")

    return incomplete

async def navigate_to_question_direct(page, target_hash):
    """Navigate directly to a question using hash navigation"""
    print(f"  Direct nav to hash: {target_hash[:50]}...")

    success = await page.evaluate(f"""
        (targetHash) => {{
            const ifr = document.querySelector('iframe');
            if (ifr && ifr.contentWindow) {{
                ifr.contentWindow.location.hash = targetHash;
                return true;
            }}
            return false;
        }}
    """, target_hash)

    if not success:
        print("  [FAIL] Could not access iframe for navigation")
        return False

    # Wait for the page to load
    print("  [OK] Hash updated, waiting for load...")

    # Get the frame after navigation
    iframe_handle = await page.wait_for_selector("iframe", timeout=10000)
    frame = await iframe_handle.content_frame()

    if not frame:
        print("  [FAIL] Could not get frame content")
        return False

    # Wait for content to load
    loaded = await wait_for_question_load(frame, timeout=15)

    if loaded:
        print("  [OK] Question loaded successfully")
        await asyncio.sleep(2)  # Extra time for rendering
        return True
    else:
        print("  [WARN] Timeout waiting for question to load")
        return False

async def detect_question_type(page):
    """Detect if the current question is MCQ or Coding"""
    iframe_handle = await page.query_selector("iframe")
    if not iframe_handle:
        return "unknown"

    frame = await iframe_handle.content_frame()
    if not frame:
        return "unknown"

    # Check for MCQ radio buttons
    has_mcq = await frame.evaluate("""() => {
        const radios = document.querySelectorAll('input[type="radio"]');
        return radios.length >= 2;
    }""")

    if has_mcq:
        return "MCQ"

    # Check for code editor
    has_coding = await frame.evaluate("""() => {
        return !!document.querySelector('.cm-content, .CodeMirror, textarea[role="textbox"], [class*="editor"]');
    }""")

    if has_coding:
        return "Coding"

    return "unknown"

async def extract_question_content(page, q_type):
    """Extract content based on question type"""
    iframe_handle = await page.query_selector("iframe")
    if not iframe_handle:
        return None, "No iframe found"

    frame = await iframe_handle.content_frame()
    if not frame:
        return None, "Could not access frame content"

    if q_type == "MCQ":
        result = await extract_mcq_content(frame)
        return result, format_mcq_output(result)
    elif q_type == "Coding":
        result = await extract_coding_content(frame)
        return result, format_coding_output(result)
    else:
        return None, f"Unknown question type: {q_type}"

async def process_questions(page, questions, max_questions=5):
    """Process multiple questions using direct link navigation"""
    results = []

    for i, question in enumerate(questions[:max_questions], 1):
        q_name = question.get('title') or question.get('text', 'Unknown')
        q_link = question.get('link')

        print(f"\n{'='*60}")
        print(f"Question {i}/{min(max_questions, len(questions))}: {q_name}")
        print('='*60)

        if not q_link:
            print(f"  [SKIP] No direct link available")
            continue

        # Extract hash from the link
        if '#' not in q_link:
            print(f"  [SKIP] Link does not contain hash: {q_link[:60]}...")
            continue

        target_hash = q_link.split('#')[-1]

        # Navigate to the question
        if not await navigate_to_question_direct(page, target_hash):
            print(f"  [FAIL] Navigation failed, skipping...")
            continue

        # Detect question type
        q_type = await detect_question_type(page)
        print(f"  Detected type: {q_type}")

        if q_type == "unknown":
            print(f"  [WARN] Could not detect question type, retrying...")
            await asyncio.sleep(3)
            q_type = await detect_question_type(page)
            print(f"  Retry detected type: {q_type}")

        # Extract content
        result_data, formatted_output = await extract_question_content(page, q_type)

        print(formatted_output)

        results.append({
            'name': q_name,
            'type': q_type,
            'link': q_link,
            'data': result_data
        })

        # Small delay between questions
        if i < min(max_questions, len(questions)):
            print(f"  Waiting before next question...")
            await asyncio.sleep(2)

    return results

async def main():
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch_persistent_context(
            USER_DATA_DIR, headless=False, args=["--start-maximized"], no_viewport=True
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        if await login_if_needed(page, load_credentials()):
            print(f"\nOpening course: {COURSE_URL}")
            await page.goto(COURSE_URL, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            ifr_handle = await page.wait_for_selector("iframe")
            frame = await ifr_handle.content_frame()

            # Show sidebar once to sync state
            await page.evaluate("""() => {
                const doc = document.querySelector('iframe').contentDocument;
                const link = Array.from(doc.querySelectorAll('a')).find(a => a.innerText.includes('Contents'));
                if (link) link.click();
            }""")
            await asyncio.sleep(3)

            # Get all incomplete questions
            incomplete_questions = await scan_sidebar_for_unfinished(page, frame)

            if incomplete_questions:
                print(f"\n{'='*60}")
                print(f"PROCESSING {min(5, len(incomplete_questions))} QUESTIONS USING DIRECT LINKS")
                print('='*60)

                # Process up to 5 questions
                results = await process_questions(page, incomplete_questions, max_questions=5)

                print(f"\n{'='*60}")
                print(f"SUMMARY: Processed {len(results)} questions")
                print('='*60)
                for r in results:
                    q_text = r['name'][:50] + '...' if len(r['name']) > 50 else r['name']
                    print(f"  - [{r['type']:6}] {q_text}")
            else:
                print("\n[OK] All questions completed!")

        print("\n" + "="*60)
        print("Processing complete. Closing browser in 5 seconds...")
        print("="*60)

        await asyncio.sleep(5)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
