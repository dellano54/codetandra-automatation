import asyncio
import os
import json
import getpass
from playwright.async_api import async_playwright

CREDENTIALS_FILE = "credentials.json"
USER_DATA_DIR = "playwright-user-data"
COURSE_URL = "https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295"

def load_credentials():
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    return None

def save_credentials(email, password):
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump({"email": email, "password": password}, f)

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

async def scan_sidebar_for_unfinished(page, frame):
    """
    Scan the sidebar to find the first unfinished question.
    First expands all unit sections to reveal the questions inside.
    Returns: (question_button_selector, question_title) or (None, None) if not found
    """
    print("Expanding all unit sections in sidebar...")

    # First, click all unit expand buttons using JavaScript on the page
    # The sidebar is inside an iframe, so we need to use the iframe context
    try:
        # Try to get the iframe element and run JS inside it
        await page.evaluate("""
            () => {
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentDocument) return 0;
                const doc = iframe.contentDocument;
                const buttons = doc.querySelectorAll('button');
                let expanded = 0;
                for (const btn of buttons) {
                    const text = btn.textContent || '';
                    // Look for unit headers like "Unit 3", "Unit 4" etc.
                    if (text.includes('Unit') && !text.includes('.')) {
                        // Check if it has an expand icon
                        const hasChevron = btn.querySelector('svg') ||
                                           btn.querySelector('[class*="chevron"]') ||
                                           btn.querySelector('[class*="arrow"]');
                        // Check if already expanded
                        const isExpanded = btn.getAttribute('aria-expanded') === 'true';
                        if (hasChevron && !isExpanded) {
                            btn.click();
                            expanded++;
                        }
                    }
                }
                return expanded;
            }
        """)
        await asyncio.sleep(1.5)
    except Exception as e:
        print(f"  Could not auto-expand units: {e}")

    print("Scanning sidebar for unfinished questions...")

    # Get all question buttons from the sidebar
    # Questions are identified by having "Question" in their text
    questions = await frame.locator('button').evaluate_all(r"""
        (buttons) => {
            const results = [];
            for (const btn of buttons) {
                const text = btn.textContent?.trim() || '';
                const title = btn.getAttribute('title') || '';

                // Check if this is a question/exercise button
                // Pattern: "4.9.1. Some Title" or contains "Question" or "Exercise"
                const questionPattern = /^\d+\.\d+\.\d+\./;
                const isQuestionPattern = questionPattern.test(title) || questionPattern.test(text);
                const isExercise = text.includes('Exercise') || title.includes('Exercise');
                const isQuestion = text.includes('Question') || title.includes('Question');

                if (isQuestionPattern || isExercise || isQuestion) {

                    // Find the SVG icon inside the button
                    const svg = btn.querySelector('svg');
                    let status = 'unknown';

                    if (svg) {
                        const svgClass = (svg.className?.baseVal || svg.className || '').toString();

                        // Check for completion status based on CSS classes
                        if (svgClass.includes('text-success')) {
                            status = 'completed';  // Green = finished
                        } else if (svgClass.includes('text-accent')) {
                            status = 'in_progress';  // Purple/pink = current/in-progress
                        } else if (!svgClass.includes('text-success')) {
                            // No success class = not started (default dark blue/gray)
                            status = 'not_started';
                        }
                    }

                    results.push({
                        text: text.substring(0, 100),
                        title: title,
                        status: status,
                        // Store button identifying info
                        buttonText: text,
                        hasQuestion: text.includes('Question') || text.includes('Exercise'),
                        isMcq: !text.includes('Exercise') && /^\d+\.\d+\.\d+\./.test(text)
                    });
                }
            }
            return results;
        }
    """)

    print(f"Found {len(questions)} question items in sidebar")

    # Filter for interactive question items
    is_interactive = lambda q: q.get('hasQuestion') or q.get('isMcq') or 'Exercise' in q['text']

    # Sort all questions by number (4.9.1, 4.9.2, 4.10.1, etc.)
    import re
    def extract_sort_key(q):
        text = q.get('text', '')
        match = re.match(r'(\d+)\.(\d+)\.(\d+)', text)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return (999, 999, 999)

    in_progress = sorted([q for q in questions if q['status'] == 'in_progress' and is_interactive(q)], key=extract_sort_key)
    not_started = sorted([q for q in questions if q['status'] == 'not_started' and is_interactive(q)], key=extract_sort_key)
    completed = [q for q in questions if q['status'] == 'completed' and is_interactive(q)]

    # Combine all incomplete sorted by number
    all_incomplete_sorted = sorted(
        [q for q in questions if q['status'] != 'completed' and is_interactive(q)],
        key=extract_sort_key
    )

    print(f"\n{'='*60}")
    print("INCOMPLETE QUESTIONS (sorted by question number):")
    print(f"{'='*60}")

    # Show status in the combined sorted list
    for i, q in enumerate(all_incomplete_sorted[:50], 1):  # Show first 50
        status_marker = "[P]" if q['status'] == 'in_progress' else "[N]"
        print(f"    {i}. {status_marker} {q['text'][:65]}")

    if len(all_incomplete_sorted) > 50:
        print(f"    ... and {len(all_incomplete_sorted) - 50} more")

    print(f"\n{'='*60}")
    print(f"COMPLETED: {len(completed)} | INCOMPLETE: {len(all_incomplete_sorted)} (P=In Progress, N=Not Started)")
    print(f"{'='*60}\n")

    # Return first incomplete by number order
    if all_incomplete_sorted:
        target = all_incomplete_sorted[0]
        status_label = "IN PROGRESS" if target['status'] == 'in_progress' else "NOT STARTED"
        print(f"Target ({status_label}): {target['text'][:80]}")
        return target
    else:
        print("All questions appear to be completed!")
        return None

async def click_question_by_title(page, frame, question_data):
    """Click on a question button by its title/text. Uses fast JavaScript click via main page."""
    title = question_data.get('title', '')
    text = question_data.get('text', '')

    print(f"Clicking: {text[:70]}...")

    import re
    import json

    # Extract unit number from question (e.g., "4.9.1." => unit 4)
    unit_match = re.match(r'(\d+)\.\d+\.\d+\.', text)
    unit_num = unit_match.group(1) if unit_match else None

    # Quick JS to expand unit and click the question
    js_title = json.dumps(title[:60])[1:-1]
    js_text = json.dumps(text[:60])[1:-1]

    try:
        result = await page.evaluate(f"""
            () => {{
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentDocument) return {{ error: 'no iframe' }};
                const doc = iframe.contentDocument;

                // Step 1: Expand unit if needed
                const unitNum = "{unit_num}";
                if (unitNum) {{
                    const unitButtons = doc.querySelectorAll('button');
                    for (const btn of unitButtons) {{
                        const btnText = btn.textContent || '';
                        if ((btnText.startsWith(unitNum + '.') || btnText.includes('Unit ' + unitNum)) && btn.querySelector('svg')) {{
                            const isExpanded = btn.getAttribute('aria-expanded') === 'true';
                            if (!isExpanded) btn.click();
                            break;
                        }}
                    }}
                }}

                // Step 2: Find and click the question button
                const buttons = doc.querySelectorAll('button');
                const searchTitle = "{js_title}";
                const searchText = "{js_text}";

                for (const btn of buttons) {{
                    const btnTitle = btn.getAttribute('title') || '';
                    const btnText = btn.textContent || '';

                    if (btnTitle.includes(searchTitle) || btnText.includes(searchText)) {{
                        btn.click();
                        return {{ success: true, text: btnText.substring(0, 60) }};
                    }}
                }}
                return {{ success: false }};
            }}
        """)

        if result and result.get('success'):
            print(f"  [OK] Clicked: {result.get('text', 'question')}")
            await asyncio.sleep(1.5)  # Short wait for load
            return True
        else:
            print(f"  [FAIL] Click failed: {result}")
            return False

    except Exception as e:
        print(f"  [ERROR] {e}")
        return False

async def detect_question_type(page):
    """Detect if current question is MCQ or Coding"""
    print("Detecting question type...")

    # Wait a bit for the question to load
    await asyncio.sleep(1)

    # Check for coding editor elements
    is_coding = await page.evaluate("""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe) return false;
        const doc = iframe.contentDocument;
        return !!(
            doc.querySelector('[role="textbox"]') ||
            doc.querySelector('.monaco-editor') ||
            doc.querySelector('.ace_editor') ||
            doc.querySelector('textarea.inputarea') ||
            doc.querySelector('.CodeMirror')
        );
    }""")

    if is_coding:
        return "Coding Task"

    # Check for MCQ elements
    is_mcq = await page.evaluate("""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe) return false;
        const doc = iframe.contentDocument;
        return !!(
            doc.querySelector('[role="radio"]') ||
            doc.querySelector('[role="checkbox"]') ||
            doc.querySelector('input[type="radio"]') ||
            doc.querySelector('input[type="checkbox"]') ||
            doc.querySelector('.option-container') ||
            doc.querySelector('.q-mcq-option')
        );
    }""")

    if is_mcq:
        return "MCQ Task"

    return "Unknown"

async def extract_mcq_content(page):
    """Extract MCQ question text and options"""
    result = await page.evaluate(r"""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe || !iframe.contentDocument) return { error: 'No iframe found' };
        const doc = iframe.contentDocument;

        // Extract question ID (from URL)
        let questionId = '';
        const urlMatch = iframe.src.match(/[?\u0026]questionId=([^\u0026]+)/);
        if (urlMatch) questionId = urlMatch[1];

        // Find the main question area (not sidebar)
        const questionArea = doc.querySelector(
            '[class*="question-container"]:not([class*="sidebar"]), ' +
            '[class*="mcq-container"], ' +
            '[class*="quiz-container"], ' +
            '.main-content [class*="question"], ' +
            'main [class*="question"]'
        ) || doc.querySelector('main') || doc.querySelector('[class*="content"]:not([class*="sidebar"])');

        const searchRoot = questionArea || doc.body;

        // Extract question text
        let questionText = '';
        const questionSelectors = [
            '.question-text',
            '.question-content',
            '[class*="question-text"]',
            '[class*="question-content"]',
            '.problem-statement',
            'h1.question',
            'h2.question',
            'h3.question',
            '.question-title'
        ];

        for (const selector of questionSelectors) {
            const el = searchRoot.querySelector(selector);
            if (el \u0026\u0026 el.textContent.trim()) {
                questionText = el.textContent.trim();
                break;
            }
        }

        // If still no text, try to find the first substantial paragraph in question area
        if (!questionText \u0026\u0026 questionArea) {
            const paras = questionArea.querySelectorAll('p');
            for (const p of paras) {
                const text = p.textContent.trim();
                if (text.length \u003e 30) {
                    questionText = text;
                    break;
                }
            }
        }

        // Extract options - ONLY look within the options/MCQ area
        const options = [];

        // Find the options container specifically
        const optionsContainer = searchRoot.querySelector(
            '[class*="options-container"], ' +
            '[class*="mcq-options"], ' +
            '[class*="answer-options"], ' +
            'form [class*="option"], ' +
            'fieldset, ' +
            '.question-options'
        );

        const optionsRoot = optionsContainer || searchRoot;

        // Strategy 1: Look for radio buttons with associated labels
        const radioInputs = optionsRoot.querySelectorAll('input[type="radio"], [role="radio"]');
        const validRadios = Array.from(radioInputs).filter(r => {
            const parent = r.closest('label, div, li');
            if (!parent) return false;
            const text = parent.textContent.trim();
            // Skip sidebar items (they have pattern like 1.1.1)
            return text.length \u003e 5 \u0026\u0026 text.length \u003c 400 \u0026\u0026 !text.match(/^\\d+\\.\\d+\\.\\d+/);
        });

        if (validRadios.length \u003e 0 \u0026\u0026 validRadios.length \u003c= 6) {
            validRadios.forEach((radio, idx) => {
                const container = radio.closest('label, div, li');
                if (!container) return;

                let text = container.textContent.trim();

                // Remove radio button text if present
                text = text.replace(/^\\s*\\u2713?\\s*/, '').trim();

                // Look for option letter
                let label = String.fromCharCode(65 + idx);
                const labelMatch = text.match(/^([A-D])[.)]?\\s*/);
                if (labelMatch) {
                    label = labelMatch[1];
                    text = text.replace(labelMatch[0], '').trim();
                }

                if (text.length \u003e 0 \u0026\u0026 text.length \u003c 400) {
                    options.push({ id: label, text: text.substring(0, 300) });
                }
            });
        }

        // Strategy 2: Look for option containers
        if (options.length === 0 || options.length \u003e 6) {
            const optionContainers = optionsRoot.querySelectorAll(
                '[class*="option-item"], [class*="option-container"]:not([class*="sidebar"]), .mcq-option'
            );

            if (optionContainers.length \u003e 0 \u0026\u0026 optionContainers.length \u003c= 6) {
                options.length = 0;
                optionContainers.forEach((container, idx) => {
                    const text = container.textContent.trim();
                    if (text.match(/^\\d+\\.\\d+\\.\\d+/)) return;
                    if (text.length \u003c 5 || text.length \u003e 400) return;

                    let label = String.fromCharCode(65 + idx);
                    const labelMatch = text.match(/^([A-D])[.)]?\\s*/);
                    if (labelMatch) {
                        label = labelMatch[1];
                    }

                    options.push({ id: label, text: text.substring(0, 300) });
                });
            }
        }

        return {
            type: 'MCQ',
            questionId: questionId,
            questionText: questionText.substring(0, 1500),
            options: options,
            optionCount: options.length
        };
    }""")

    return result

async def extract_coding_content(page):
    """Extract coding question text and pre-written code info"""
    result = await page.evaluate("""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe || !iframe.contentDocument) return { error: 'No iframe found' };
        const doc = iframe.contentDocument;

        // Extract question ID
        let questionId = '';
        const urlMatch = iframe.src.match(/[?&]questionId=([^&]+)/);
        if (urlMatch) questionId = urlMatch[1];

        // Extract question text
        let questionText = '';
        const questionSelectors = [
            '.question-text',
            '[data-testid="question-text"]',
            '.problem-statement',
            '.coding-question',
            'h1',
            'h2',
            '.description',
            '[class*="description"]',
            '[class*="problem"]'
        ];

        for (const selector of questionSelectors) {
            const el = doc.querySelector(selector);
            if (el && el.textContent.trim()) {
                questionText = el.textContent.trim();
                break;
            }
        }

        // If no specific element, try content area
        if (!questionText) {
            const content = doc.querySelector('.content, .problem-container, .question-container');
            if (content) {
                const text = content.textContent.trim();
                // Get first paragraph
                const lines = text.split('\\n').filter(l => l.trim());
                if (lines.length > 0) questionText = lines[0].substring(0, 500);
            }
        }

        // Extract code editor content and pre-written info
        let codeInfo = {
            hasPreWrittenCode: false,
            preWrittenLines: [],
            writeAboveLines: [],
            writeBelowLines: [],
            hints: []
        };

        // Look for code editor
        const editorSelectors = [
            '.monaco-editor',
            '.ace_editor',
            '.CodeMirror',
            '[role="textbox"]',
            'textarea.inputarea',
            '.code-editor',
            'pre code',
            '.code-block'
        ];

        let codeElement = null;
        for (const selector of editorSelectors) {
            codeElement = doc.querySelector(selector);
            if (codeElement) break;
        }

        if (codeElement) {
            // Try to get initial code content
            let initialCode = codeElement.textContent || codeElement.value || '';

            // Check for placeholder comments or instructions
            const codeLines = initialCode.split('\\n');
            codeLines.forEach((line, idx) => {
                const trimmed = line.trim();

                // Look for comments indicating where to write
                if (trimmed.includes('WRITE YOUR CODE HERE') ||
                    trimmed.includes('Write your code here') ||
                    trimmed.includes('Your code here') ||
                    trimmed.includes('// TODO') ||
                    trimmed.includes('# TODO') ||
                    trimmed.includes('/* TODO') ||
                    trimmed.includes('pass') ||
                    trimmed.includes('// Write')) {
                    codeInfo.writeAboveLines.push({ line: idx + 1, content: trimmed });
                    codeInfo.hasPreWrittenCode = true;
                }

                // Look for pre-existing code (non-comment, non-empty lines that aren't TODO)
                if (trimmed.length > 0 &&
                    !trimmed.startsWith('//') &&
                    !trimmed.startsWith('#') &&
                    !trimmed.startsWith('/*') &&
                    !trimmed.startsWith('*') &&
                    !trimmed.startsWith('*/') &&
                    !trimmed.includes('TODO') &&
                    !trimmed.includes('pass')) {
                    codeInfo.preWrittenLines.push({ line: idx + 1, content: trimmed });
                }
            });

            codeInfo.totalLines = codeLines.length;
        }

        // Look for instructions about code placement
        const instructionSelectors = [
            '.instructions',
            '.hints',
            '[class*="hint"]',
            '[class*="instruction"]',
            '.code-instruction'
        ];

        instructionSelectors.forEach(selector => {
            const els = doc.querySelectorAll(selector);
            els.forEach(el => {
                const text = el.textContent.trim();
                if (text && text.length > 5) {
                    codeInfo.hints.push(text.substring(0, 200));

                    // Check for specific placement instructions
                    if (text.toLowerCase().includes('above') || text.toLowerCase().includes('before')) {
                        codeInfo.writeAboveLines.push({ hint: text.substring(0, 100) });
                    }
                    if (text.toLowerCase().includes('below') || text.toLowerCase().includes('after')) {
                        codeInfo.writeBelowLines.push({ hint: text.substring(0, 100) });
                    }
                }
            });
        });

        return {
            type: 'Coding',
            questionId: questionId,
            questionText: questionText.substring(0, 2000),
            codeInfo: codeInfo
        };
    }""")

    return result

async def click_resume_button(frame):
    """Click the Resume button on the dashboard to resume in-progress question"""
    try:
        # Look for Resume button in the main content area
        # The Resume button appears in the "Pickup from where you left off!" section
        resume_btn = frame.locator('button:has-text("Resume")').first
        if await resume_btn.count() > 0 and await resume_btn.is_visible():
            await resume_btn.click()
            print("Clicked Resume button on dashboard")
            await asyncio.sleep(2)
            return True
    except Exception as e:
        print(f"Resume button click failed: {e}")
    return False

# Store for tracking incomplete questions across function calls
incomplete_questions_cache = []
current_question_index = -1

async def open_course_and_find_first_unfinished(page):
    """Navigate to course and open first unfinished question"""
    global incomplete_questions_cache, current_question_index

    print(f"Navigating to course: {COURSE_URL}")
    await page.goto(COURSE_URL, wait_until="domcontentloaded")

    # Wait for iframe to load
    await page.wait_for_selector("iframe", timeout=30000)
    frame = page.frame_locator("iframe").first

    print("Waiting for course content to load...")
    await asyncio.sleep(2)

    # First, navigate to Contents page where the sidebar with questions is visible
    try:
        contents_link = frame.locator('a:has-text("Contents")').first
        if await contents_link.count() > 0:
            await contents_link.click()
            print("Clicked Contents link")
            await asyncio.sleep(2)
        else:
            # If no Contents link, try Resume button which also loads the question view
            await click_resume_button(frame)
            await asyncio.sleep(2)
    except Exception as e:
        print(f"Could not click Contents: {e}")
        # Fall back to Resume button
        await click_resume_button(frame)
        await asyncio.sleep(2)

    # Now scan the sidebar (it's visible after navigating to Contents)
    question_data = await scan_sidebar_for_unfinished(page, frame)

    if not question_data:
        print("No unfinished questions found.")
        return "No unfinished questions"

    # Store all incomplete questions for later navigation
    # Re-scan to populate the cache with all incomplete questions
    all_questions = await get_all_incomplete_questions(page, frame)
    incomplete_questions_cache = all_questions
    current_question_index = 0  # Start at the first one

    print(f"\n[CACHE] Stored {len(incomplete_questions_cache)} incomplete questions for navigation")

    # Click on the first unfinished question
    success = await click_question_by_title(page, frame, question_data)

    if success:
        await asyncio.sleep(2)
        question_type = await detect_question_type(page)
        return question_type
    else:
        return "Failed to click question"

async def get_all_incomplete_questions(page, frame):
    """Get all incomplete questions from the sidebar for caching"""
    import re
    questions = await frame.locator('button').evaluate_all(r"""
        (buttons) => {
            const results = [];
            for (const btn of buttons) {
                const text = btn.textContent?.trim() || '';
                const title = btn.getAttribute('title') || '';

                // Check if this is a question/exercise button
                const questionPattern = /^\d+\.\d+\.\d+\./;
                const isQuestionPattern = questionPattern.test(title) || questionPattern.test(text);
                const isExercise = text.includes('Exercise') || title.includes('Exercise');
                const isQuestion = text.includes('Question') || title.includes('Question');

                if (isQuestionPattern || isExercise || isQuestion) {
                    const svg = btn.querySelector('svg');
                    let status = 'unknown';

                    if (svg) {
                        const svgClass = (svg.className?.baseVal || svg.className || '').toString();
                        if (svgClass.includes('text-success')) {
                            status = 'completed';
                        } else if (svgClass.includes('text-accent')) {
                            status = 'in_progress';
                        } else {
                            status = 'not_started';
                        }
                    }

                    // Only include incomplete questions
                    if (status !== 'completed') {
                        results.push({
                            text: text.substring(0, 100),
                            title: title,
                            status: status,
                            buttonText: text
                        });
                    }
                }
            }
            return results;
        }
    """)

    # Sort by question number (e.g., 4.9.1, 4.9.2, 4.10.1, etc.)
    def extract_sort_key(q):
        text = q.get('text', '')
        # Extract numbers like "4.9.1" or "4.10.1" from the beginning
        match = re.match(r'(\d+)\.(\d+)\.(\d+)', text)
        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return (999, 999, 999)  # Put non-matching at the end

    return sorted(questions, key=extract_sort_key)

async def move_to_next_unfinished_question(page):
    """Move to the next unfinished question from the cached list"""
    global incomplete_questions_cache, current_question_index

    if not incomplete_questions_cache:
        print("[ERROR] No incomplete questions cached. Run open_course_and_find_first_unfinished first.")
        return "No cache available"

    current_question_index += 1

    if current_question_index >= len(incomplete_questions_cache):
        print(f"\n[COMPLETE] All {len(incomplete_questions_cache)} questions processed!")
        return "All questions completed"

    next_question = incomplete_questions_cache[current_question_index]
    print(f"\n[NAVIGATING] Question {current_question_index + 1}/{len(incomplete_questions_cache)}:")
    print(f"  -> {next_question['text'][:70]}")

    # Get the frame
    frame = page.frame_locator("iframe").first

    # Make sure we're on the Contents page
    try:
        contents_link = frame.locator('a:has-text("Contents")').first
        if await contents_link.count() > 0 and await contents_link.is_visible():
            await contents_link.click()
            await asyncio.sleep(1.5)
    except:
        pass

    # Click the next question
    success = await click_question_by_title(page, frame, next_question)

    if success:
        await asyncio.sleep(2)
        question_type = await detect_question_type(page)
        print(f"\n[STATUS] Question {current_question_index + 1}/{len(incomplete_questions_cache)}: {question_type}")
        return question_type
    else:
        return "Failed to click next question"

async def main():
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=["--start-maximized"],
            no_viewport=True,
            ignore_https_errors=True
        )

        page = await browser.new_page()
        if len(browser.pages) > 1:
            await browser.pages[0].close()

        credentials = load_credentials()

        if await login_if_needed(page, credentials):
            # First, open the course and go to first unfinished question
            status = await open_course_and_find_first_unfinished(page)
            print(f"\nSTATUS: {status}")

            # Extract and display question content
            print("\n" + "="*60)
            print("EXTRACTING QUESTION CONTENT...")
            print("="*60)

            if status == "MCQ Task":
                mcq_data = await extract_mcq_content(page)
                print(f"\n[MCQ QUESTION]")
                print(f"ID: {mcq_data.get('questionId', 'N/A')}")
                print(f"\nQuestion:\n{mcq_data.get('questionText', 'N/A')[:500]}...")
                print(f"\nOptions ({mcq_data.get('optionCount', 0)} found):")
                for opt in mcq_data.get('options', []):
                    print(f"  {opt['id']}. {opt['text'][:100]}...")

            elif status == "Coding Task":
                coding_data = await extract_coding_content(page)
                print(f"\n[CODING QUESTION]")
                print(f"ID: {coding_data.get('questionId', 'N/A')}")
                print(f"\nQuestion:\n{coding_data.get('questionText', 'N/A')[:500]}...")

                code_info = coding_data.get('codeInfo', {})
                print(f"\nCode Info:")
                print(f"  Has Pre-written Code: {code_info.get('hasPreWrittenCode', False)}")
                print(f"  Total Lines: {code_info.get('totalLines', 0)}")

                if code_info.get('preWrittenLines', []):
                    print(f"\n  Pre-written code lines:")
                    for line in code_info['preWrittenLines'][:5]:
                        print(f"    Line {line['line']}: {line['content'][:60]}...")

                if code_info.get('writeAboveLines', []):
                    print(f"\n  Write ABOVE/BEFORE these lines:")
                    for item in code_info['writeAboveLines'][:3]:
                        print(f"    {item.get('line', 'N/A')}: {item.get('content', item.get('hint', ''))[:60]}...")

                if code_info.get('writeBelowLines', []):
                    print(f"\n  Write BELOW/AFTER these lines:")
                    for item in code_info['writeBelowLines'][:3]:
                        print(f"    {item.get('line', 'N/A')}: {item.get('content', item.get('hint', ''))[:60]}...")

                if code_info.get('hints', []):
                    print(f"\n  Hints/Instructions:")
                    for hint in code_info['hints'][:3]:
                        print(f"    - {hint[:80]}...")

            else:
                print(f"Unknown question type, skipping extraction")

            # TEST: Move to next unfinished question
            print("\n" + "="*60)
            print("TESTING: Move to next unfinished question...")
            print("="*60)
            await asyncio.sleep(3)

            next_status = await move_to_next_unfinished_question(page)
            print(f"\nNEXT STATUS: {next_status}")

            # Extract next question too if it's different type
            if next_status == "Coding Task" and status == "MCQ Task":
                print("\n" + "="*60)
                print("EXTRACTING CODING QUESTION CONTENT...")
                print("="*60)
                coding_data = await extract_coding_content(page)
                print(f"\n[CODING QUESTION]")
                print(f"ID: {coding_data.get('questionId', 'N/A')}")
                print(f"\nQuestion:\n{coding_data.get('questionText', 'N/A')[:500]}...")

        else:
            print("Automation stopped due to login failure.")

        print("\nPress Enter in this terminal to close the browser...")
        await asyncio.to_thread(input)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
