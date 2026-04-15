import asyncio
import json
import os
from playwright.async_api import async_playwright

USER_DATA_DIR = "playwright-user-data"
COURSE_URL = "https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295"

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

        page = browser.pages[0] if browser.pages else await browser.new_page()

        print(f"Navigating to course: {COURSE_URL}")
        await page.goto(COURSE_URL, wait_until="domcontentloaded")

        # Wait for iframe to load
        await page.wait_for_selector("iframe", timeout=30000)
        frame_element = await page.query_selector("iframe")
        frame = await frame_element.content_frame()

        print("Waiting for course content to load...")
        await asyncio.sleep(5)

        # Try to navigate to Contents
        try:
            contents_link = await frame.query_selector('a:has-text("Contents")')
            if contents_link:
                await contents_link.click()
                print("Clicked Contents link")
                await asyncio.sleep(3)
        except Exception as e:
            print(f"Could not click Contents: {e}")

        # Expand all units
        print("Expanding all units...")
        await frame.evaluate("""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            for (const btn of buttons) {
                const text = btn.innerText.trim();
                if (text.includes('Unit') && !text.includes('.')) {
                    const isExpanded = btn.getAttribute('aria-expanded') === 'true';
                    if (!isExpanded) btn.click();
                }
            }
        }""")
        await asyncio.sleep(3)

        # Find first question button and click it
        question_btn_handle = await frame.evaluate_handle(r"""() => {
            const buttons = Array.from(document.querySelectorAll('button'));
            const questionPattern = /^\d+\.\d+\.\d+\./;
            const btn = buttons.find(b => {
                const text = b.innerText.trim();
                const title = b.getAttribute('title') || '';
                return questionPattern.test(text) || 
                       questionPattern.test(title) || 
                       text.includes('Exercise') || 
                       title.includes('Exercise') ||
                       text.includes('Question') ||
                       title.includes('Question');
            });
            return btn;
        }""")

        if question_btn_handle and not await question_btn_handle.evaluate("x => x === undefined || x === null"):
            btn_info = await question_btn_handle.evaluate("x => ({ text: x.innerText.trim(), title: x.getAttribute('title') })")
            print(f"Clicking: '{btn_info['text']}' title: '{btn_info['title']}'")
            
            # Click it using JS to avoid visibility issues
            await question_btn_handle.evaluate("x => x.click()")
            print("Clicked via JS. Waiting for navigation...")
            await asyncio.sleep(5)
            
            # IMPORTANT: The hash we want is inside the IFRAME window
            results = await page.evaluate("""() => {
                const iframe = document.querySelector('iframe');
                if (!iframe || !iframe.contentWindow) return { error: 'no iframe' };
                return {
                    iframeSrc: iframe.src,
                    iframeHash: iframe.contentWindow.location.hash,
                    mainUrl: window.location.href,
                    mainHash: window.location.hash
                };
            }""")
            
            print(json.dumps(results, indent=2))
            
            if results.get('iframeHash'):
                # Construct possible direct link
                # Typically it's Course URL + iframe hash
                base_course_url = COURSE_URL.split('#')[0]
                direct_link = base_course_url + results['iframeHash']
                print(f"\nPROPOSED DIRECT LINK: {direct_link}")
        else:
            print("No question button found.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
