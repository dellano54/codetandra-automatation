import asyncio
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
        
        print("Navigating to course URL...")
        await page.goto(COURSE_URL, wait_until="networkidle")
        
        print("Waiting for iframe...")
        await page.wait_for_selector('iframe[src*="lms-course.html"]', timeout=30000)
        frame = page.frame_locator('iframe[src*="lms-course.html"]').first
        
        print("Waiting 5 seconds...")
        await asyncio.sleep(5)
        
        print("Clicking Resume...")
        await frame.locator("body").evaluate("""() => {
            const allElements = Array.from(document.querySelectorAll('*'));
            const resumeBtn = allElements.find(el => el.innerText && el.innerText.trim() === 'Resume' && (el.tagName === 'BUTTON' || el.tagName === 'DIV' || el.tagName === 'A'));
            if (resumeBtn) resumeBtn.click();
        }""")
        
        print("Waiting 10 seconds for the viewer to load...")
        await asyncio.sleep(10)
        
        print("Opening sidebar...")
        await frame.locator("body").evaluate("""() => {
            // Find the toggle button on the left
            // It might have class containing 'toggle' or 'menu' or SVG inside
            const buttons = Array.from(document.querySelectorAll('button'));
            // Look for a button that is position absolute or fixed on the left
            // Or just try to find the menu button by position
            for (let b of buttons) {
                const rect = b.getBoundingClientRect();
                if (rect.left < 50 && rect.width < 50 && rect.height > 0) {
                    console.log("Clicking possible menu toggle", b);
                    b.click();
                    break;
                }
            }
        }""")
        
        await asyncio.sleep(5)
        
        print("Taking screenshot with sidebar open...")
        await page.screenshot(path="screenshot_sidebar.png")
        print("Saved screenshot_sidebar.png")
        
        print("Scraping sidebar items...")
        data = await frame.locator("body").evaluate("""() => {
            const items = Array.from(document.querySelectorAll('*'));
            return items.map(i => {
                const text = (i.innerText || "").trim();
                return { tag: i.tagName, class: i.className, text: text.substring(0, 80) };
            }).filter(i => i.text.length > 0 && typeof i.class === 'string' && (i.class.includes('tree-item') || i.class.includes('node') || i.class.includes('menu')));
        }""")
        
        for idx, item in enumerate(data):
            print(f"[{item['tag']}] class='{item['class']}': {item['text']}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
