import asyncio
import os
import json
from playwright.async_api import async_playwright
from main import login_if_needed, load_credentials, navigate_to_question_direct, wait_for_question_load

USER_DATA_DIR = "playwright-user-data"
COURSE_URL = "https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295"
# Target question 4.9.4 (Coding)
TARGET_HASH = "/eucs/6937cd430cc4f7020deb0295/contents/6937cd430cc4f7020deb0295/6937cd430cc4f7020deb0299/6937cd430cc4f7020deb02b8"

async def debug():
    async with async_playwright() as p:
        print("Launching browser...")
        browser = await p.chromium.launch_persistent_context(
            USER_DATA_DIR, headless=False, args=["--start-maximized"], no_viewport=True
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        if await login_if_needed(page, load_credentials()):
            print(f"Opening course...")
            await page.goto(COURSE_URL, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            # Navigate to target question
            print(f"Navigating to {TARGET_HASH}...")
            await navigate_to_question_direct(page, TARGET_HASH)
            
            # Wait for content
            iframe_handle = await page.wait_for_selector("iframe")
            frame = await iframe_handle.content_frame()
            await wait_for_question_load(frame)
            await asyncio.sleep(5) # Give it extra time

            print("Taking screenshot...")
            await page.screenshot(path="debug_coding_question.png")
            
            print("Dumping frame HTML...")
            html = await frame.content()
            with open("debug_frame.html", "w", encoding="utf-8") as f:
                f.write(html)
            
            print("Inspecting editor...")
            editor_info = await frame.evaluate("""() => {
                const editors = [];
                // Check for CodeMirror
                const cm5 = document.querySelectorAll('.CodeMirror');
                cm5.forEach((el, i) => {
                    editors.push({
                        type: 'CodeMirror 5',
                        classes: el.className,
                        hasInstance: !!el.CodeMirror,
                        index: i
                    });
                });
                
                // Check for CM6
                const cm6 = document.querySelectorAll('.cm-content');
                cm6.forEach((el, i) => {
                    editors.push({
                        type: 'CodeMirror 6',
                        classes: el.className,
                        index: i
                    });
                });

                // Check for generic textareas
                const textareas = document.querySelectorAll('textarea');
                textareas.forEach((el, i) => {
                    editors.push({
                        type: 'textarea',
                        id: el.id,
                        name: el.name,
                        role: el.getAttribute('role'),
                        index: i
                    });
                });

                // Check for Timer
                const timers = [];
                const possibleTimers = document.querySelectorAll('[class*="timer"], [id*="timer"]');
                possibleTimers.forEach(el => {
                    timers.push({
                        tag: el.tagName,
                        text: el.innerText,
                        classes: el.className,
                        color: window.getComputedStyle(el).color,
                        bgColor: window.getComputedStyle(el).backgroundColor
                    });
                });

                return { editors, timers };
            }""")
            
            print(json.dumps(editor_info, indent=2))
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug())
