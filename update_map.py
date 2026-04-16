import asyncio
import json
import os
from playwright.async_api import async_playwright

USER_DATA_DIR = "playwright-user-data"
EUC_ID = "6937cd430cc4f7020deb0295"
MAP_FILE = "memory/verified_question_map.json"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(USER_DATA_DIR, headless=True)
        page = browser.pages[0] if browser.pages else await browser.new_page()
        
        await page.goto(f"https://srmeaswari.codetantra.com/secure/course.jsp?eucId={EUC_ID}")
        await asyncio.sleep(5)
        
        api_url = f"https://srmeaswari.codetantra.com/secure/rest/a2/euc/gecc?eucId={EUC_ID}"
        print(f"Fetching course structure from {api_url}...")
        
        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const response = await fetch('{api_url}');
                    return await response.json();
                }} catch (e) {{
                    return {{ error: e.message }};
                }}
            }}
        """)
        
        if result and result.get('result') == 0:
            data = result.get('data', {})
            contents = data.get('contents', [])
            
            new_map = {}
            # contents -> list of units
            for u_idx, unit in enumerate(contents, 1):
                unit_id = unit.get('id')
                # units have 'contents' too (topics)
                topics = unit.get('contents', [])
                for t_idx, topic in enumerate(topics, 1):
                    topic_id = topic.get('id')
                    # topics have 'contents' (leafs/lessons)
                    leafs = topic.get('contents', [])
                    for l_idx, leaf in enumerate(leafs, 1):
                        leaf_id = leaf.get('id')
                        prefix = f"{u_idx}.{t_idx}.{l_idx}"
                        name = leaf.get('name', 'Unknown')
                        link = f"#/eucs/{EUC_ID}/contents/{unit_id}/{topic_id}/{leaf_id}"
                        new_map[prefix] = {
                            "link": link,
                            "name": name
                        }
            
            os.makedirs("memory", exist_ok=True)
            with open(MAP_FILE, "w", encoding='utf-8') as f:
                json.dump(new_map, f, indent=2)
            print(f"Successfully updated map with {len(new_map)} items.")
        else:
            print(f"Failed to fetch data: {result}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
