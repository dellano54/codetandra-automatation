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

async def open_course_and_analyze(page):
    print(f"Navigating to course: {COURSE_URL}")
    # Navigate using commit to start the poll as early as possible
    await page.goto(COURSE_URL, wait_until="domcontentloaded")

    print("Extreme Speed Detection Active...")
    start_time = asyncio.get_event_loop().time()
    
    while asyncio.get_event_loop().time() - start_time < 40:
        try:
            # Re-locate frame on every iteration to handle potential reloads/navigation
            frame = page.frame_locator("iframe").first
            
            # Execute a single fast JS check that handles both Resume click and Question detection
            res = await frame.locator("body").evaluate("""() => {
                // 1. Success condition: Question Markers
                const isCoding = !!document.querySelector('[role="textbox"], .monaco-editor, .ace_editor, textarea.inputarea');
                if (isCoding) return { status: "Coding Task" };
                
                const isMCQ = !!document.querySelector('[role="radio"], [role="checkbox"], input[type="radio"], input[type="checkbox"], .option-container');
                if (isMCQ) return { status: "MCQ Task" };
                
                // 2. Action condition: Resume button (click immediately if found)
                const resumeBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Resume'));
                if (resumeBtn && resumeBtn.offsetParent !== null) {
                    resumeBtn.click();
                    return { status: "resume_clicked" };
                }
                
                return { status: "searching" };
            }""")
            
            if res["status"] in ["Coding Task", "MCQ Task"]:
                return res["status"]
            
        except Exception:
            # Context destroyed or frame not ready - retry immediately without delay
            pass
            
        await asyncio.sleep(0.1) # 100ms check frequency
    
    return "Timeout/Unknown"

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
            status = await open_course_and_analyze(page)
            print(f"\nSTATUS: {status}")
        else:
            print("Automation stopped due to login failure.")
        
        print("\nPress Enter in this terminal to close the browser...")
        await asyncio.to_thread(input)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
