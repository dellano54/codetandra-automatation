import asyncio
import os
import json
import getpass
import datetime
import sys
from playwright.async_api import async_playwright

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

USER_DATA_DIR = "playwright-user-data"
CREDENTIALS_FILE = "credentials.json"
COURSE_URL = "https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295"
CACHE_FILE = "memory/question_cache.json"
SOLUTIONS_FILE = "memory/solutions.json"

from extraction_funcs import (
    extract_coding_content, extract_solved_mcq_answer, wait_for_question_load
)

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

def load_solutions():
    if os.path.exists(SOLUTIONS_FILE):
        try:
            with open(SOLUTIONS_FILE, "r", encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_solutions(solutions):
    os.makedirs("memory", exist_ok=True)
    with open(SOLUTIONS_FILE, "w", encoding='utf-8') as f:
        json.dump(solutions, f, indent=2)

async def login(page, email, password):
    print(f"Checking login status for {email}...", flush=True)
    await page.goto("https://srmeaswari.codetantra.com/login.jsp", wait_until="domcontentloaded")
    
    if "home.jsp" in page.url:
        current_email = await page.evaluate("() => document.querySelector('.user-email')?.innerText || ''")
        if current_email.lower() == email.lower():
            print("Already logged in to correct account.", flush=True)
            return True
        
        print(f"Logged in as {current_email}, logging out to switch to {email}...", flush=True)
        logout_success = await page.evaluate("""() => {
            const logoutBtn = Array.from(document.querySelectorAll('a, button')).find(el => 
                (el.innerText.includes('Logout') || el.classList.contains('btn-danger')) && 
                window.getComputedStyle(el).display !== 'none'
            );
            if (logoutBtn) { logoutBtn.click(); return true; }
            return false;
        }""")
        if not logout_success:
            print("  [WARN] Could not find logout button, login might fail.", flush=True)
        
        await page.wait_for_url("**/login.jsp", timeout=15000)

    print(f"Entering credentials for {email}...", flush=True)
    await page.wait_for_selector("#loginEmail", timeout=10000)
    await page.fill("#loginEmail", email)
    await page.fill("#loginPassword", password)
    await page.evaluate("() => { const b = document.getElementById('loginBtn'); if(b) { b.classList.remove('disabled'); b.removeAttribute('disabled'); } }")
    await page.click("#loginBtn")
    try:
        await page.wait_for_url("**/home.jsp", timeout=15000)
        return True
    except:
        return False

async def scan_sidebar(page, frame):
    verified_map = {}
    if os.path.exists("memory/verified_question_map.json"):
        with open("memory/verified_question_map.json", "r", encoding='utf-8') as f:
            verified_map = json.load(f)

    print("Scanning questions...", flush=True)
    await page.evaluate("() => { const ifr = document.querySelector('iframe'); if(!ifr) return; const doc = ifr.contentDocument; Array.from(doc.querySelectorAll('details')).forEach(d => d.open = true); }")
    await asyncio.sleep(2)

    sidebar_items = await frame.locator('button').evaluate_all(r"""
        (buttons) => {
            const results = [];
            for (const btn of buttons) {
                const text = btn.textContent?.trim() || '';
                const match = text.match(/^(\d+\.\d+\.\d+\.)\s*(.*)$/);
                if (match) {
                    const prefix = match[1];
                    const svg = btn.querySelector('svg');
                    let status = 'not_started';
                    if (svg) {
                        const cls = (svg.className?.baseVal || '').toString();
                        if (cls.includes('text-success')) status = 'completed';
                        else if (cls.includes('text-accent')) status = 'in_progress';
                    }
                    results.push({ prefix, label: match[2].trim(), status, title: btn.getAttribute('title') || '' });
                }
            }
            return results;
        }
    """)

    cache = load_cache()
    processed = []
    for side_q in sidebar_items:
        clean_prefix = side_q['prefix'].rstrip('.')
        link = verified_map.get(clean_prefix, {}).get('link')
        q_label = side_q['title'] or side_q['prefix'] + " " + side_q['label']
        
        processed.append({
            "prefix": clean_prefix,
            "text": q_label,
            "status": side_q['status'],
            "link": link
        })
        cache[clean_prefix] = {"text": q_label, "link": link, "status": side_q['status']}
    
    save_cache(cache)
    return processed

async def navigate_to_hash(page, target_hash):
    if not target_hash: return False
    if not target_hash.startswith('#'): target_hash = '#' + target_hash
    await page.evaluate(f"document.querySelector('iframe').contentWindow.location.hash = '{target_hash}'")
    iframe_handle = await page.wait_for_selector("iframe")
    frame = await iframe_handle.content_frame()
    return await wait_for_question_load(frame)

async def handle_late_submission(frame):
    try:
        trap = await frame.evaluate("""() => {
            const container = document.querySelector('.ReasonForLateSubmissionContainer') || 
                            Array.from(document.querySelectorAll('div, span')).find(el => 
                                (el.innerText.includes('Reason for late submission') || 
                                 el.innerText.includes('Please enter at least 15 characters')) &&
                                window.getComputedStyle(el).display !== 'none'
                            );
            if (container) {
                const btn = Array.from(container.querySelectorAll('button, div[role="button"]'))
                                 .find(b => b.innerText.includes('OK') || b.innerText.includes('Submit'));
                if (btn) btn.click();
                else container.click();
                return true;
            }
            return false;
        }""")
        return trap
    except: pass
    return False

async def wait_for_success(frame, timeout=180):
    """Wait logic prioritizing the Green Timer and platform success signals."""
    for sec in range(0, timeout, 2):
        await handle_late_submission(frame)
        res = await frame.evaluate(r"""() => {
            const body = document.body.innerText;
            
            // 1. Success Signals
            const greenTimer = Array.from(document.querySelectorAll('.badge-success')).find(el => window.getComputedStyle(el).display !== 'none');
            const testMatch = body.match(/(\d+) out of (\d+) test case\(s\) passed/);
            const allPassed = !!testMatch && parseInt(testMatch[1]) === parseInt(testMatch[2]) && parseInt(testMatch[2]) > 0;
            const isCorrect = body.includes('Correct') && !body.includes('Incorrect');
            
            if (greenTimer || allPassed || isCorrect) return { state: "SUCCESS", text: greenTimer ? greenTimer.innerText : (allPassed ? testMatch[0] : "Correct") };
            
            // 2. Running Signals
            const isRunning = !!document.querySelector('svg animate') || 
                              !!Array.from(document.querySelectorAll('.badge-warning')).find(el => window.getComputedStyle(el).display !== 'none') ||
                              body.includes('Running') || body.includes('Preparing');
            
            if (isRunning) return { state: "RUNNING" };
            
            // 3. Potential Error Signals
            const errorEl = Array.from(document.querySelectorAll('.bg-error, .text-error')).find(el => {
                const isLateTrap = el.closest('.ReasonForLateSubmissionContainer') || el.innerText.includes('characters');
                return !isLateTrap && window.getComputedStyle(el).display !== 'none';
            });
            if (errorEl) return { state: "ERROR", text: errorEl.innerText.substring(0, 40) };
            
            return { state: "IDLE" };
        }""")
        
        if res['state'] == "SUCCESS":
            print(f"  [SUCCESS] {res['text']}", flush=True)
            return True
            
        if sec % 10 == 0:
            msg = f"  ... {res['state']} ({sec}s)"
            if res['state'] == "ERROR": msg += f" - {res['text']}..."
            print(msg, flush=True)
            
        await asyncio.sleep(2)
    return False

async def wait_for_editor(frame):
    for _ in range(30):
        if not await frame.evaluate("() => document.body.innerText.includes('Setting up environment')"):
            if await frame.evaluate("() => !!document.querySelector('.cm-content, .CodeMirror, [role=\"textbox\"]')"):
                return True
        await asyncio.sleep(2)
    return False

async def click_submit(frame):
    await handle_late_submission(frame)
    for _ in range(3):
        success = await frame.evaluate("""() => {
            let btn = document.querySelector('button[accesskey="s"]');
            if (!btn) {
                btn = Array.from(document.querySelectorAll('button')).find(b => 
                    b.innerText.includes('Submit') && b.classList.contains('btn-success')
                );
            }
            if (btn && !btn.disabled) { 
                btn.click(); 
                return true; 
            }
            return false;
        }""")
        if not success: await frame.press("body", "Alt+s")
        await asyncio.sleep(1)
        # Check if submit accepted (button disabled or gone)
        is_done = await frame.evaluate("""() => {
            const btn = document.querySelector('button[accesskey="s"]');
            return !btn || btn.disabled || window.getComputedStyle(btn).display === 'none';
        }""")
        if is_done: return True
        await handle_late_submission(frame)
    return False

async def detect_q_type(frame):
    has_editor = await frame.evaluate("() => !!document.querySelector('.cm-content, .CodeMirror, .ace_editor, [role=\"textbox\"]')")
    if has_editor: return "Coding"
    has_options = await frame.evaluate("() => document.querySelectorAll('input.checkbox, input.radio, input[type=\"checkbox\"], input[type=\"radio\"]').length >= 2")
    if has_options: return "MCQ"
    return "unknown"

async def extract_answers(page, questions):
    solutions = load_solutions()
    print(f"\n[EXTRACTION] Total: {len(questions)}", flush=True)
    for i, q in enumerate(questions, 1):
        prefix = q['prefix']
        if not q['link']: continue
        print(f"[{i}/{len(questions)}] Extracting [{prefix}]: {q['text']}", flush=True)
        if not await navigate_to_hash(page, q['link']): continue
        await asyncio.sleep(2)
        frame = (await (await page.wait_for_selector("iframe")).content_frame())
        q_type = await detect_q_type(frame)
        if q_type == "MCQ":
            ans = await extract_solved_mcq_answer(frame)
            if ans: solutions[prefix] = {"type": "MCQ", "answer": ans, "name": q['text']}
        elif q_type == "Coding":
            await wait_for_editor(frame)
            res = await extract_coding_content(frame)
            if res and res.get('codeTemplate'):
                solutions[prefix] = {"type": "Coding", "answer": res['codeTemplate'], "name": q['text']}
        if i % 10 == 0: save_solutions(solutions)
    save_solutions(solutions)

async def fill_answers(page, incomplete):
    solutions = load_solutions()
    print(f"\n[FILLING] Total: {len(incomplete)}", flush=True)
    for i, q in enumerate(incomplete, 1):
        prefix = q['prefix']
        sol = solutions.get(prefix)
        if not sol: continue
        print(f"[{i}/{len(incomplete)}] Filling [{prefix}]: {q['text']}", flush=True)
        if not await navigate_to_hash(page, q['link']): continue
        await asyncio.sleep(2)
        frame = (await (await page.wait_for_selector("iframe")).content_frame())
        await handle_late_submission(frame)
        
        if sol['type'] == "MCQ":
            await frame.evaluate("""() => {
                const inputs = document.querySelectorAll('input.checkbox, input.radio, input[type="checkbox"], input[type="radio"]');
                inputs.forEach(i => { if(i.checked && i.type.includes('check')) i.click(); });
            }""")
            await asyncio.sleep(1)
            await frame.evaluate(f"""(letters) => {{ 
                const inputs = document.querySelectorAll('input.checkbox, input.radio, input[type=\"checkbox\"], input[type=\"radio\"]');
                letters.forEach(l => {{ 
                    const idx = l.charCodeAt(0)-65; 
                    if(inputs[idx]) inputs[idx].click(); 
                }}); 
            }}""", sol['answer'])
        else:
            await wait_for_editor(frame)
            await frame.evaluate(f"""(code) => {{
                const cm6 = document.querySelector('.cm-content');
                if (cm6 && cm6.cmView) {{
                    const view = cm6.cmView.view;
                    view.dispatch({{ changes: {{from: 0, to: view.state.doc.length, insert: code}} }});
                }} else {{
                    const cm5 = document.querySelector('.CodeMirror');
                    if(cm5 && cm5.CodeMirror) cm5.CodeMirror.setValue(code);
                }}
            }}""", sol['answer'])

        await asyncio.sleep(1) # Final buffer for registration
        await click_submit(frame)
        print("  Waiting for completion verification...", flush=True)
        if not await wait_for_success(frame):
            print("  [WARN] Could not verify success. Moving to next.", flush=True)
        await asyncio.sleep(1)

async def main():
    print("\n--- CodeTantra Direct Copy Tool (NO AI) ---")
    print("1. Extract Answers (Source ID)")
    print("2. Fill Answers (Target ID)")
    choice = input("Select mode (1/2): ")
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, args=["--start-maximized"], no_viewport=True)
        page = browser.pages[0]
        email = input("Email: ")
        pw = getpass.getpass("Password: ")
        if await login(page, email, pw):
            await page.goto(COURSE_URL)
            await asyncio.sleep(5)
            await page.evaluate("() => { const ifr = document.querySelector('iframe'); if(ifr && ifr.contentDocument) { const l = Array.from(ifr.contentDocument.querySelectorAll('a')).find(a => a.innerText.includes('Contents')); ifl = l; if(l) l.click(); } }")
            await asyncio.sleep(3)
            frame = (await (await page.wait_for_selector("iframe")).content_frame())
            questions = await scan_sidebar(page, frame)
            if choice == '1': await extract_answers(page, questions)
            else:
                incomplete = [q for q in questions if q['status'] != 'completed']
                await fill_answers(page, incomplete)
        print("\n[FINISH] Execution complete. Check the browser. Press Enter to close.")
        input()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
