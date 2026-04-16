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
    sys.stdout.reconfigure(encoding='utf-8')

USER_DATA_DIR = "playwright-user-data"
CREDENTIALS_FILE = "credentials.json"
COURSE_URL = "https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295"
CACHE_FILE = "memory/question_cache.json"

from gemini_utils import analyze_mcq, analyze_coding
from extraction_funcs import extract_mcq_content, extract_coding_content, format_mcq_output, format_coding_output, wait_for_question_load

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
    print("Navigating to login page...", flush=True)
    try:
        await page.goto("https://srmeaswari.codetantra.com/login.jsp", wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"Initial navigation failed ({e}), retrying once...", flush=True)
        await asyncio.sleep(2)
        await page.goto("https://srmeaswari.codetantra.com/login.jsp", wait_until="domcontentloaded", timeout=30000)

    if "home.jsp" in page.url:
        print("Already logged in via session.", flush=True)
        return True

    if not credentials:
        print("\nNo credentials found. Please enter them.", flush=True)
        email = input("Email: ")
        password = getpass.getpass("Password: ")
        save_credentials(email, password)
        credentials = {"email": email, "password": password}

    print(f"Logging in as {credentials['email']}...", flush=True)
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
        print("Login successful!", flush=True)
        return True
    except Exception:
        print("Login redirection failed. Please check your credentials.", flush=True)
        return False

async def fetch_course_contents(page):
    """Fetch the full course structure and IDs via the REST API"""
    print("Fetching course contents structure...", flush=True)
    try:
        current_url = page.url
        if 'eucId=' in current_url:
            euc_id = current_url.split('eucId=')[1].split('&')[0].split('#')[0]
        else:
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
            print(f"  [WARN] Failed to fetch contents: {result.get('error') or result.get('msg')}", flush=True)
            return None
    except Exception as e:
        print(f"  [ERROR] Error fetching contents: {e}", flush=True)
        return None

async def scan_sidebar_for_unfinished(page, frame):
    """Scan sidebar, update cache with links and status, return incomplete questions list"""
    verified_map = {}
    map_path = "memory/verified_question_map.json"
    if os.path.exists(map_path):
        with open(map_path, "r", encoding='utf-8') as f:
            verified_map = json.load(f)
        print(f"Loaded {len(verified_map)} verified links from JSON map.", flush=True)

    print("Expanding all sidebar units and lessons...", flush=True)
    await page.evaluate("""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe || !iframe.contentDocument) return;
        const doc = iframe.contentDocument;
        const expandAll = () => {
            const allDetails = Array.from(doc.querySelectorAll('details'));
            let openedAny = false;
            for (const details of allDetails) {
                if (!details.open) {
                    details.open = true;
                    openedAny = true;
                }
            }
            return openedAny;
        };
        for (let i = 0; i < 3; i++) {
            if (!expandAll()) break;
        }
    }""")
    await asyncio.sleep(2)

    print("Scanning sidebar for question status...", flush=True)
    sidebar_items = await frame.locator('button').evaluate_all(r"""
        (buttons) => {
            const results = [];
            for (const btn of buttons) {
                const text = btn.textContent?.trim() || '';
                const title = btn.getAttribute('title') || '';
                const match = text.match(/^(\d+\.\d+\.\d+\.)\s*(.*)$/);
                if (match) {
                    const prefix = match[1];
                    const label = match[2].trim();
                    const svg = btn.querySelector('svg');
                    let status = 'not_started';
                    if (svg) {
                        const cls = (svg.className?.baseVal || svg.className || '').toString();
                        if (cls.includes('text-success')) status = 'completed';
                        else if (cls.includes('text-accent')) status = 'in_progress';
                    }
                    results.push({ prefix, label, status, title });
                }
            }
            return results;
        }
    """)

    cache = load_cache()
    processed_questions = []
    for side_q in sidebar_items:
        clean_prefix = side_q['prefix'].rstrip('.')
        link = None
        if clean_prefix in verified_map:
            link = verified_map[clean_prefix]['link']
        q_label = side_q['title'] or side_q['prefix'] + " " + side_q['label']
        processed_questions.append({
            "text": q_label,
            "status": side_q['status'],
            "link": link
        })
        cache[q_label] = {
            "link": link,
            "status": side_q['status'],
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    save_cache(cache)
    incomplete = [q for q in processed_questions if q['status'] != 'completed' and q['link']]
    print(f"\n{'='*60}\nINCOMPLETE QUESTIONS ({len(incomplete)} total):\n{'='*60}", flush=True)
    for i, q in enumerate(incomplete[:15], 1):
        status_char = 'I' if q['status'] == 'in_progress' else 'N'
        print(f"{i:2}. [{status_char}] {q['text'][:55]}...", flush=True)
    return incomplete

async def navigate_to_question_direct(page, target_hash):
    """Navigate directly to a question using hash navigation"""
    if not target_hash.startswith('#'): target_hash = '#' + target_hash
    print(f"  Direct nav to hash: {target_hash}", flush=True)
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
        print("  [FAIL] Could not access iframe for navigation", flush=True)
        return False
    print("  [OK] Hash updated, waiting for load...", flush=True)
    iframe_handle = await page.wait_for_selector("iframe", timeout=10000)
    frame = await iframe_handle.content_frame()
    if not frame: return False
    loaded = await wait_for_question_load(frame, timeout=15)
    if loaded:
        print("  [OK] Question loaded successfully", flush=True)
        await asyncio.sleep(0.5)
        return True
    return False

async def detect_question_type(page):
    """Detect if the current question is MCQ or Coding"""
    iframe_handle = await page.query_selector("iframe")
    if not iframe_handle: return "unknown"
    frame = await iframe_handle.content_frame()
    if not frame: return "unknown"
    has_mcq = await frame.evaluate("""() => {
        const inputs = document.querySelectorAll('input[type="radio"], input[type="checkbox"]');
        return inputs.length >= 2;
    }""")
    if has_mcq: return "MCQ"
    has_coding = await frame.evaluate("""() => {
        return !!document.querySelector('.cm-content, .CodeMirror, .ace_editor, [class*="editor"]');
    }""")
    if has_coding: return "Coding"
    return "unknown"

async def extract_question_content(page, q_type):
    """Extract content based on question type"""
    iframe_handle = await page.query_selector("iframe")
    if not iframe_handle: return None, "No iframe found"
    frame = await iframe_handle.content_frame()
    if not frame: return None, "Could not access frame content"
    if q_type == "MCQ":
        result = await extract_mcq_content(frame)
        return result, format_mcq_output(result)
    elif q_type == "Coding":
        result = await extract_coding_content(frame)
        return result, format_coding_output(result)
    return None, f"Unknown question type: {q_type}"

async def handle_late_submission(frame):
    """Handle the reason for late submission trap and full-screen overlays"""
    try:
        # Check for both the standard container and the full-screen overlay
        trap_info = await frame.evaluate("""() => {
            // Find specific late submission containers
            const lateContainer = document.querySelector('.ReasonForLateSubmissionContainer') || 
                                 Array.from(document.querySelectorAll('div, span')).find(el => 
                                    (el.innerText.includes('Reason for late submission') || 
                                     el.innerText.includes('Please enter at least 15 characters')) &&
                                     window.getComputedStyle(el).display !== 'none'
                                 );
            
            // Find full-screen overlays that might be blocking (bg-opacity-95 is common for these)
            const fullOverlay = Array.from(document.querySelectorAll('div')).find(el => {
                const style = window.getComputedStyle(el);
                return style.position === 'fixed' && 
                       style.zIndex && parseInt(style.zIndex) > 10 &&
                       (el.classList.contains('bg-opacity-95') || el.innerText.includes('Reason for late submission'));
            });

            const container = lateContainer || fullOverlay;
            if (container) {
                const style = window.getComputedStyle(container);
                const isVisible = style.display !== 'none' && style.visibility !== 'hidden';
                return { isVisible, text: container.innerText, isFullOverlay: !!fullOverlay };
            }
            return { isVisible: false };
        }""")
        
        if trap_info['isVisible']:
            print(f"  [TRAP] Late submission/Overlay detected, bypassing...", flush=True)
            await frame.evaluate("""() => {
                const findContainer = () => {
                    const lateContainer = document.querySelector('.ReasonForLateSubmissionContainer') || 
                                         Array.from(document.querySelectorAll('div, span')).find(el => 
                                            (el.innerText.includes('Reason for late submission') || 
                                             el.innerText.includes('Please enter at least 15 characters')) &&
                                             window.getComputedStyle(el).display !== 'none'
                                         );
                    const fullOverlay = Array.from(document.querySelectorAll('div')).find(el => {
                        const style = window.getComputedStyle(el);
                        return style.position === 'fixed' && style.zIndex && parseInt(style.zIndex) > 10 &&
                               (el.classList.contains('bg-opacity-95') || el.innerText.includes('Reason for late submission'));
                    });
                    return lateContainer || fullOverlay;
                };

                const container = findContainer();
                if (container) {
                    // Try clicking OK/Submit buttons inside first
                    const innerBtn = Array.from(container.querySelectorAll('button, div[role="button"]'))
                                          .find(b => b.innerText.includes('OK') || b.innerText.includes('Submit'));
                    if (innerBtn) { 
                        innerBtn.click(); 
                    } else {
                        // Click the whole container/overlay background
                        container.click();
                    }
                    
                    // Force dispatch events
                    container.dispatchEvent(new Event('mousedown', { bubbles: true }));
                    container.dispatchEvent(new Event('mouseup', { bubbles: true }));
                }
            }""")
            await asyncio.sleep(1)
            return True
    except Exception as e:
        print(f"  [ERROR] Error handling late submission: {e}", flush=True)
    return False

async def solve_mcq(page, frame, extraction_result, max_retries=3, screenshot=None):
    """Analyze and solve MCQ with retries and memory of failed combinations"""
    failed_combinations = []
    is_multiple = extraction_result.get('isMultiple', False)
    
    for attempt in range(max_retries):
        print(f"  MCQ Attempt {attempt + 1}/{max_retries}...", flush=True)
        answer_letters = await analyze_mcq(
            extraction_result['question'], 
            extraction_result['options'],
            images=extraction_result.get('images', []),
            screenshot=screenshot,
            failed_combinations=failed_combinations,
            is_multiple=is_multiple
        )
        print(f"  Gemini Answer: {', '.join(answer_letters)}", flush=True)
        if not answer_letters:
            print("  [FAIL] AI did not provide any answer letters.", flush=True)
            continue
        await frame.evaluate("""
            (isMultiple) => {
                const inputs = Array.from(document.querySelectorAll(isMultiple ? 'input.checkbox, input[type="checkbox"]' : 'input.radio, input[type="radio"]'));
                inputs.forEach(i => { if(i.checked) i.click(); });
            }
        """, is_multiple)
        success = await frame.evaluate("""
            ([letters, isMultiple]) => {
                let clickedCount = 0;
                const inputs = Array.from(document.querySelectorAll(isMultiple ? 'input.checkbox, input[type="checkbox"]' : 'input.radio, input[type="radio"]'));
                letters.forEach(letter => {
                    const index = letter.charCodeAt(0) - 65;
                    if (inputs[index]) {
                        inputs[index].click();
                        clickedCount++;
                    } else {
                        const labels = Array.from(document.querySelectorAll('label, div, span, p'));
                        for (const el of labels) {
                            const text = el.innerText.trim();
                            if (text.startsWith(letter + '.') || text === letter) {
                                el.click();
                                clickedCount++;
                                break;
                            }
                        }
                    }
                });
                return clickedCount > 0;
            }
        """, [answer_letters, is_multiple])
        
        if success:
            print(f"  [OK] Selected options: {', '.join(answer_letters)}", flush=True)
            await asyncio.sleep(1)
            print("  [OK] Clicking Submit...", flush=True)
            try:
                # Find all potential submit buttons
                # Button 3 in snapshot is at the bottom right next to next button
                # Selector targets button with 'Submit' text and accesskey='s' which is unique to that button
                submit_locator = frame.locator('button:has-text("Submit")[accesskey="s"], button.btn-success:has-text("Submit")')
                
                await handle_late_submission(frame)
                
                # Check for the specific bottom-right button and wait for it
                target_btn = submit_locator.last # 'last' usually picks the one further down in DOM
                await target_btn.wait_for(state="visible", timeout=10000)
                
                for _ in range(10):
                    is_disabled = await target_btn.evaluate("el => el.disabled")
                    if not is_disabled: break
                    await handle_late_submission(frame)
                    await asyncio.sleep(1)
                
                # Try clicking. If intercepted, use JS click on the specific element
                try:
                    await target_btn.click(timeout=3000, force=True)
                except:
                    await target_btn.evaluate("el => el.click()")
            except Exception as e:
                print(f"  [WARN] Submit interaction failed ({e}), trying final JS fallback...", flush=True)
                await frame.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('Submit'));
                    // Sort by Y coordinate descending to find the one at the bottom
                    btns.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                    const submitBtn = btns.find(b => !b.disabled) || btns[0];
                    if (submitBtn) {
                        submitBtn.click();
                    } else {
                        window.dispatchEvent(new KeyboardEvent('keydown', { altKey: true, key: 's', code: 'KeyS' }));
                    }
                }""")
            await asyncio.sleep(2)
            await handle_late_submission(frame)
            print("  Waiting for success verification...", flush=True)
            for wait_idx in range(6):
                await asyncio.sleep(5)
                await handle_late_submission(frame)
                feedback = await frame.evaluate("""() => {
                    const body = document.body.innerText;
                    const hasIncorrect = body.includes('Incorrect') || body.includes('Wrong') || body.includes('Try again');
                    const timer = Array.from(document.querySelectorAll('.badge, .clock, [class*="timer"], .badge-success')).find(el => {
                        const style = window.getComputedStyle(el);
                        const bg = style.backgroundColor;
                        const isGreen = bg.includes('rgb(9, 190, 139)') || bg.includes('rgb(0, 128, 0)');
                        const hasSuccessClass = el.classList.contains('badge-success');
                        return isGreen || hasSuccessClass;
                    });
                    return { hasIncorrect, isSuccess: !!timer, timerText: timer ? timer.innerText : "" };
                }""")
                if feedback['isSuccess']:
                    print(f"  [SUCCESS] Answer {', '.join(answer_letters)} was correct! ({feedback['timerText']})", flush=True)
                    return True
                if feedback['hasIncorrect']:
                    print(f"  [FAIL] Answer {', '.join(answer_letters)} was incorrect.", flush=True)
                    failed_combinations.append(answer_letters)
                    if is_multiple:
                        await frame.evaluate("""() => {
                            const inputs = document.querySelectorAll('input.checkbox, input[type="checkbox"]');
                            inputs.forEach(i => { if(i.checked) i.click(); });
                        }""")
                    break 
            print(f"  [WARN] Attempt {attempt + 1} did not result in a green timer.", flush=True)
        else:
            print(f"  [FAIL] Could not find requested options.", flush=True)
    return False

async def solve_coding(page, frame, extraction_result, max_retries=3, screenshot=None, override_code=None):
    """Analyze and solve Coding problem with retries and feedback"""
    error_feedback = ""
    for attempt in range(max_retries):
        print(f"  Coding Attempt {attempt + 1}/{max_retries}...", flush=True)
        
        if override_code:
            solution_code = override_code
        else:
            current_code = await frame.evaluate("""() => {
                const cm6 = document.querySelector('.cm-content');
                if (cm6 && cm6.cmView) return cm6.cmView.view.state.doc.toString();
                const cm5 = document.querySelector('.CodeMirror');
                if (cm5 && cm5.CodeMirror) return cm5.CodeMirror.getValue();
                const ta = document.querySelector('textarea[role="textbox"]') || document.querySelector('textarea');
                return ta ? ta.value : "";
            }""")
            solution_code = await analyze_coding(
                extraction_result['question'], 
                current_code or extraction_result['codeTemplate'],
                "",
                error_feedback,
                images=extraction_result.get('images', []),
                screenshot=screenshot
            )
        print("  Writing solution to editor...", flush=True)
        success = await frame.evaluate(f"""
            (code) => {{
                const cm6 = document.querySelector('.cm-content');
                if (cm6 && cm6.cmView) {{
                    const view = cm6.cmView.view;
                    view.dispatch({{ changes: {{from: 0, to: view.state.doc.length, insert: code}} }});
                    return true;
                }}
                const cm5 = document.querySelector('.CodeMirror');
                if (cm5 && cm5.CodeMirror) {{ cm5.CodeMirror.setValue(code); return true; }}
                const ta = document.querySelector('textarea[role="textbox"]') || document.querySelector('textarea');
                if (ta) {{
                    ta.value = code;
                    ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    ta.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    return true;
                }}
                return false;
            }}
        """, solution_code)
        if success:
            print("  [OK] Solution written. Clicking Submit...", flush=True)
            await asyncio.sleep(1)
            try:
                # Target the bottom-right submit button specifically
                submit_locator = frame.locator('button:has-text("Submit")[accesskey="s"], button.btn-success:has-text("Submit")')

                await handle_late_submission(frame)
                target_btn = submit_locator.last
                await target_btn.wait_for(state="visible", timeout=10000)

                for _ in range(10):
                    is_disabled = await target_btn.evaluate("el => el.disabled")
                    if not is_disabled: break
                    await handle_late_submission(frame)
                    await asyncio.sleep(1)

                try:
                    await target_btn.click(timeout=3000, force=True)
                except:
                    await target_btn.evaluate("el => el.click()")
            except Exception as e:
                print(f"  [WARN] Submit interaction failed ({e}), trying final JS fallback...", flush=True)
                await frame.evaluate("""() => {
                    const btns = Array.from(document.querySelectorAll('button')).filter(b => b.innerText.includes('Submit'));
                    btns.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
                    const submitBtn = btns.find(b => !b.disabled) || btns[0];
                    if (submitBtn) {
                        submitBtn.click();
                    } else {
                        window.dispatchEvent(new KeyboardEvent('keydown', { altKey: true, key: 's', code: 'KeyS' }));
                    }
                }""")

            await asyncio.sleep(2)
            await handle_late_submission(frame)
            print("  Waiting for execution results...", flush=True)
            execution_started = False
            for wait_sec in range(20):
                await asyncio.sleep(5)
                status = await frame.evaluate("""() => {
                    const body = document.body.innerText;
                    const isRunning = !!document.querySelector('svg animate') || body.includes('Running') || body.includes('Preparing');
                    const timer = Array.from(document.querySelectorAll('.badge, .clock, [class*="timer"], .badge-success')).find(el => {
                        const style = window.getComputedStyle(el);
                        const bg = style.backgroundColor;
                        const isGreen = bg.includes('rgb(9, 190, 139)') || bg.includes('rgb(0, 128, 0)');
                        const hasSuccessClass = el.classList.contains('badge-success');
                        return isGreen || hasSuccessClass;
                    });
                    const testMatch = body.match(/(\\d+) out of (\\d+) test case\\(s\\) passed/);
                    const allPassedText = !!testMatch && parseInt(testMatch[1]) === parseInt(testMatch[2]) && parseInt(testMatch[2]) > 0;
                    const isSuccess = allPassedText || (!!timer && execution_started);
                    const errorContainer = document.querySelector('.bg-error') || document.querySelector('.text-error');
                    const hasFailed = !!errorContainer || (!!testMatch && parseInt(testMatch[1]) < parseInt(testMatch[2]) && !isRunning);
                    let error = errorContainer ? errorContainer.innerText : "";
                    return { isRunning, allPassedText, isSuccess, hasFailed, error, timerText: timer ? timer.innerText : "" };
                }""")
                if status['isRunning']:
                    execution_started = True
                    print(f"  [INFO] Execution in progress...", flush=True)
                    continue
                if status['allPassedText'] or (status['isSuccess'] and execution_started):
                    print(f"  [SUCCESS] Question solved! (Timer: {status['timerText']})", flush=True)
                    return True
                if status['hasFailed'] and not status['isRunning']:
                    print(f"  [ERROR] Execution failed: {status['error'][:100]}...", flush=True)
                    error_feedback = status['error'] or "Test cases failed."
                    break
                if not execution_started and wait_sec > 2:
                    if await handle_late_submission(frame):
                        print("  [TRAP] Handled during wait loop.", flush=True)
                        continue
                print(f"  [INFO] Waiting... (Started: {execution_started})", flush=True)
            print(f"  [WARN] Attempt {attempt + 1} failed.", flush=True)
        else:
            print("  [FAIL] Editor interaction failed.", flush=True)
    return False

async def wait_for_editor_ready(frame, timeout=60):
    print("  Waiting for editor environment to setup...", flush=True)
    for i in range(timeout // 2):
        is_loading = await frame.evaluate("""() => { return document.body.innerText.includes('Setting up environment'); }""")
        if not is_loading:
            has_submit = await frame.evaluate("""() => { return !!Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Submit')); }""")
            if has_submit:
                print("  [OK] Editor environment ready.", flush=True)
                return True
        await asyncio.sleep(2)
    return False

async def process_questions(page, questions, max_questions=5):
    results = []
    for i, question in enumerate(questions[:max_questions], 1):
        q_name = question.get('text') or 'Unknown'
        q_link = question.get('link')
        print(f"\n{'='*60}\nQuestion {i}/{min(max_questions, len(questions))}: {q_name}\n{'='*60}", flush=True)
        if not q_link: 
            print(f"  [SKIP] No link found for {q_name}", flush=True)
            continue
        if not await navigate_to_question_direct(page, q_link): 
            print(f"  [SKIP] Direct navigation failed for {q_name}", flush=True)
            continue
        await asyncio.sleep(2)
        iframe_handle = await page.wait_for_selector("iframe", timeout=15000)
        frame = await iframe_handle.content_frame()
        if not frame: 
            print(f"  [SKIP] Could not access frame for {q_name}", flush=True)
            continue
        q_type = "unknown"
        for detect_attempt in range(3):
            await wait_for_question_load(frame, timeout=15)
            q_type = await detect_question_type(page)
            if q_type != "unknown": break
            print(f"  [INFO] Type detection attempt {detect_attempt+1} failed, retrying...", flush=True)
            await asyncio.sleep(3)
        print(f"  Detected type: {q_type}", flush=True)
        if q_type == "unknown":
            print(f"  [SKIP] Could not determine question type for {q_name}", flush=True)
            results.append({'name': q_name, 'type': 'unknown', 'link': q_link, 'solved': False})
            continue
        if q_type == "Coding": await wait_for_editor_ready(frame)
        result_data, formatted_output = await extract_question_content(page, q_type)
        if not result_data:
            print(f"  [INFO] Content extraction failed, retrying...", flush=True)
            await asyncio.sleep(5)
            result_data, formatted_output = await extract_question_content(page, q_type)
        if not result_data:
            print(f"  [SKIP] Could not extract content for {q_name}", flush=True)
            results.append({'name': q_name, 'type': q_type, 'link': q_link, 'solved': False})
            continue
        print(formatted_output, flush=True)
        screenshot_bytes = None
        try:
            target_selector = result_data.get('selector')
            if target_selector:
                screenshot_bytes = await frame.locator(target_selector).screenshot(type='png')
            else:
                screenshot_bytes = await iframe_handle.screenshot(type='png')
            print("  [OK] Question screenshot captured.", flush=True)
        except Exception as e:
            print(f"  [WARN] Failed to capture surgical screenshot: {e}", flush=True)
            try: screenshot_bytes = await iframe_handle.screenshot(type='png')
            except: pass
        solved = False
        if q_type == "MCQ": solved = await solve_mcq(page, frame, result_data, screenshot=screenshot_bytes)
        elif q_type == "Coding": 
            # Check for 4.9.17 override
            override = None
            if q_link and "67814f3fac8e20004581b813" in q_link:
                print("  [INFO] Applying user override for 4.9.17", flush=True)
                override = """SELECT 
    od.product_id, 
    p.name, 
    o.customer_id, 
    o.total_amount, 
    od.unit_price 
FROM products p 
RIGHT JOIN order_details od ON p.product_id = od.product_id 
LEFT JOIN orders o ON od.order_id = o.order_id;"""
            
            solved = await solve_coding(page, frame, result_data, screenshot=screenshot_bytes, override_code=override)
        if solved:
            print(f"  [OK] Question {i} solved.", flush=True)
            await asyncio.sleep(1)
        results.append({'name': q_name, 'type': q_type, 'link': q_link, 'data': result_data})
        await asyncio.sleep(0.5)
    return results

async def main():
    async with async_playwright() as p:
        print("Launching browser...", flush=True)
        browser = await p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, args=["--start-maximized"], no_viewport=True)
        page = browser.pages[0] if browser.pages else await browser.new_page()
        if await login_if_needed(page, load_credentials()):
            await page.goto(COURSE_URL, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            ifr_handle = await page.wait_for_selector("iframe")
            frame = await ifr_handle.content_frame()
            await page.evaluate("""() => {
                const doc = document.querySelector('iframe').contentDocument;
                const link = Array.from(doc.querySelectorAll('a')).find(a => a.innerText.includes('Contents'));
                if (link) link.click();
            }""")
            await asyncio.sleep(3)
            incomplete_questions = await scan_sidebar_for_unfinished(page, frame)
            if incomplete_questions:
                await process_questions(page, incomplete_questions, max_questions=len(incomplete_questions))
            else:
                print("\n[OK] All questions completed!", flush=True)
        await asyncio.sleep(5)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
