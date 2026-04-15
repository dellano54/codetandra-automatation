# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **CodeTantra Course Automation** project using Playwright for browser automation. It automates interactions with the CodeTantra learning platform (`srmeaswari.codetantra.com`) for a Database Management Systems course.

## Common Commands

### Running the Main Application
```bash
# Run the main automation script (requires virtual environment)
.venv/Scripts/python.exe main.py

# Or using the virtual environment directly
python main.py
```

### Virtual Environment
```bash
# Activate virtual environment (Windows)
.venv/Scripts/activate

# The project uses Python 3.13 with Playwright installed
```

### Utility Scripts
```bash
# Fetch course contents via API
python fetch_course_contents.py

# Extract MCQ content from current page
python extract_mcq_tmp.py

# Debug extraction functions
python debug_extraction.py

# Check question URLs
python check_question_url.py

# Test extraction logic
python test_extraction.py
```

## Architecture & Key Files

### Core Files
- **`main.py`** - Primary entry point. Handles login, sidebar scanning, question navigation, and content extraction
- **`extraction_funcs.py`** - Contains `extract_mcq_content()` and `extract_coding_content()` for extracting question data from the iframe
- **`fetch_course_contents.py`** - Captures course structure via REST API interception using Playwright's response handler

### Configuration & Data
- **`credentials.json`** - Stores login credentials (email/password) - auto-created on first run
- **`course_contents.json`** - Cached course structure from the REST API
- **`memory/question_cache.json`** - Tracks question status (completed/in_progress/not_started) and direct links
- **`.env`** - Contains `GOOGLE_API_KEY` for external API usage

### Browser Automation
- Uses **Playwright** with Chromium in non-headless mode (`headless=False`)
- **Persistent browser context** stored in `playwright-user-data/` directory
- Launches with `--start-maximized` and `no_viewport=True` for full desktop experience

## Platform-Specific Patterns

### CodeTantra Structure
The platform uses an iframe-based architecture:
- Main page URL: `https://srmeaswari.codetantra.com/secure/course.jsp?eucId=6937cd430cc4f7020deb0295`
- Content is rendered inside an iframe with src containing `lms-course.html`
- Direct navigation uses hash URLs: `#/eucs/[EUC_ID]/contents/[UNIT_ID]/[LESSON_ID]/[QUESTION_ID]`

### Key Selectors
- **Editor**: `[role="textbox"], .cm-content, .CodeMirror`
- **Submit button**: `[keyshortcuts="Alt+s"]`
- **Next button**: `[keyshortcuts="Alt+n"]`
- **Sidebar items**: `button` elements with aria-expanded attributes
- **Question status indicators**: SVG icons with `text-success` (completed), `text-accent` (in_progress)

### Question Types
1. **MCQ** - Multiple choice questions with radio buttons (`input[type="radio"]`), extracted via `extract_mcq_content()`
2. **Coding** - SQL/PLpgSQL exercises with code editor, extracted via `extract_coding_content()`

### Completion Criteria
- **Timer turns green** at top of exercise indicates successful completion
- For coding: `n/n test case(s) passed` message appears
- Sidebar status colors: Green=completed, Pink/Accent=in_progress

### Important Platform Behaviors
- **Late Submission trap**: A "Reason for late submission" field appears to detect automation. Strategy: Click the container/button directly without typing a reason
- **Direct navigation**: Use `iframe.contentWindow.location.hash = targetHash` for faster navigation than clicking sidebar
- **API endpoint**: `https://srmeaswari.codetantra.com/secure/rest/a2/euc/gecc?eucId=[ID]` returns full course structure

## Development Patterns

### Frame Handling
Most interactions require evaluating JavaScript inside the iframe:
```python
iframe_handle = await page.query_selector("iframe")
frame = await iframe_handle.content_frame()
result = await frame.evaluate("""() => { ... })""")
```

### Caching Strategy
- `scan_sidebar_for_unfinished()` in main.py updates `memory/question_cache.json` with status and direct links
- Questions are sorted by numeric pattern (e.g., `4.9.3.`) for sequential processing
- Cache includes `last_updated` timestamps for tracking

### Batch Processing Approach
- Target 5 questions per turn for efficiency
- Step 1: Scrape requirements
- Step 2: Execute solutions
- Step 3: Handle "Late Submission" dialog in same script turn

## Testing & Debugging

- Various `debug_*.py` and `dump_*.py` files exist for troubleshooting extraction
- Screenshots saved as `screenshot*.png` for visual debugging
- HTML dumps (`*_dump.html`) captured for DOM inspection
- Chrome DevTools MCP is configured for browser automation

## Security Notes

- Credentials stored locally in `credentials.json`
- `.gitignore` excludes `credentials.json`, `.env`, and `playwright-user-data/`
- `memory/question_cache.json` is tracked and contains question links but no sensitive data
