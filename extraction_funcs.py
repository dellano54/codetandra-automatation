"""
Extraction functions for CodeTantra questions.
Handles MCQ and Coding question content extraction from the iframe.
"""
import asyncio

async def extract_mcq_content(frame):
    """
    Extract MCQ question content and options from the frame.
    Returns a dictionary with question text, options, images, and type info.
    """
    js_code = r"""
    () => {
        try {
            const questionSelectors = [
                '.question-text', '.question-content', '.mcq-question', 
                '[class*="question"]', 'h4', '.problem-statement', '.ql-editor', '[role="main"]'
            ];
            let questionText = '';
            const images = [];
            let selectorFound = '';

            for (const selector of questionSelectors) {
                const el = document.querySelector(selector);
                if (el && el.innerText.trim().length > 10) {
                    // Check if it's the container and not the options list
                    if (!el.querySelector('input[type="radio"], input[type="checkbox"]')) {
                        questionText = el.innerText.trim();
                        selectorFound = selector;
                        
                        const imgElements = el.querySelectorAll('img');
                        imgElements.forEach(img => {
                            if (img.src && !img.src.includes('data:image/svg+xml')) {
                                try {
                                    const canvas = document.createElement('canvas');
                                    canvas.width = img.naturalWidth || img.width;
                                    canvas.height = img.naturalHeight || img.height;
                                    const ctx = canvas.getContext('2d');
                                    ctx.drawImage(img, 0, 0);
                                    images.push(canvas.toDataURL('image/png'));
                                } catch (e) {
                                    images.push(img.src);
                                }
                            }
                        });
                        if (questionText.length > 20) break;
                    }
                }
            }

            if (!questionText) {
                const allText = document.body.innerText;
                const radioIndex = allText.indexOf('A.');
                if (radioIndex > 50) questionText = allText.substring(0, radioIndex).trim();
            }

            const checkboxInputs = document.querySelectorAll('input.checkbox, input[type="checkbox"]');
            const radioInputs = document.querySelectorAll('input.radio, input[type="radio"]');
            
            const isMultiple = checkboxInputs.length > 0 || document.body.innerText.includes('Select all the correct options');
            const inputs = isMultiple ? checkboxInputs : radioInputs;

            const options = [];
            inputs.forEach((input, index) => {
                const label = input.closest('label') || input.parentElement;
                if (label) {
                    let text = label.innerText.trim().replace(/^\s*[\u25cb\u25c9\u25ef]?\s*/, '');
                    if (text) options.push({ letter: String.fromCharCode(65 + index), text: text });
                }
            });

            return {
                question: questionText || 'Content not found',
                options: options,
                images: images,
                selector: selectorFound,
                isMultiple: isMultiple
            };
        } catch (e) {
            return { question: 'Error: ' + e.message, options: [], images: [], isMultiple: false };
        }
    }
    """
    return await frame.evaluate(js_code)

async def extract_coding_content(frame):
    """
    Extract coding question content from the frame.
    """
    js_code = r"""
    () => {
        try {
            const problemSelectors = [
                '.problem-statement', '.coding-question', '.question-text', 
                '[class*="question-content"]', '.content-area', '.ql-editor', '[role="main"]', 'h4'
            ];
            let problemText = '';
            const images = [];
            let selectorFound = '';

            for (const selector of problemSelectors) {
                const el = document.querySelector(selector);
                if (el && el.innerText.trim().length > 30) {
                    const text = el.innerText.trim();
                    if (!text.includes('function opendialog') || text.includes('Table')) {
                        problemText = text;
                        selectorFound = selector;
                        
                        const imgElements = el.querySelectorAll('img');
                        imgElements.forEach(img => {
                            if (img.src && !img.src.includes('data:image/svg+xml')) {
                                try {
                                    const canvas = document.createElement('canvas');
                                    canvas.width = img.naturalWidth || img.width;
                                    canvas.height = img.naturalHeight || img.height;
                                    const ctx = canvas.getContext('2d');
                                    ctx.drawImage(img, 0, 0);
                                    images.push(canvas.toDataURL('image/png'));
                                } catch (e) {
                                    images.push(img.src);
                                }
                            }
                        });
                        if (problemText.length > 100) break;
                    }
                }
            }

            // Fallback: look for any div with significant text that looks like a problem
            if (!problemText) {
                const divs = Array.from(document.querySelectorAll('div'));
                const bestDiv = divs.find(d => d.innerText.length > 200 && (d.innerText.includes('Table') || d.innerText.includes('Write a')));
                if (bestDiv) {
                    problemText = bestDiv.innerText.trim();
                    selectorFound = 'div'; // Broad fallback
                }
            }

            let codeTemplate = '';
            const el = document.querySelector('.cm-content, [role="textbox"], .CodeMirror');
            if (el) {
                if (el.cmView && el.cmView.view) codeTemplate = el.cmView.view.state.doc.toString();
                else codeTemplate = el.innerText || el.value || '';
            }

            return {
                question: problemText || 'Coding problem content not found',
                codeTemplate: codeTemplate,
                images: images,
                selector: selectorFound
            };
        } catch (e) {
            return { question: 'Error: ' + e.message, codeTemplate: '', images: [] };
        }
    }
    """
    return await frame.evaluate(js_code)

async def wait_for_question_load(frame, timeout=15):
    """Wait for the question content to load in the frame."""
    js_code = r"""
    () => {
        const hasMCQ = document.querySelectorAll('input').length >= 2;
        const hasCoding = !!document.querySelector('.cm-content, [role="textbox"], .CodeMirror');
        const hasQuestion = !!document.querySelector('.question-text, .problem-statement, h4, .ql-editor');
        return (hasMCQ || hasCoding || hasQuestion);
    }
    """
    for i in range(timeout):
        try:
            if await frame.evaluate(js_code): return True
        except: pass
        await asyncio.sleep(1)
    return False

def format_mcq_output(result):
    if not result: return "Failed"
    out = [f"TYPE: {'MULTIPLE' if result.get('isMultiple') else 'SINGLE'} MCQ", "="*50, result.get('question', 'Text not extracted')]
    if result.get('images'): out.append(f"[Found {len(result['images'])} images in question area]")
    out.append("\nOptions:")
    for opt in result.get('options', []): out.append(f"  {opt['letter']}. {opt['text']}")
    return "\n".join(out)

def format_coding_output(result):
    if not result: return "Failed"
    out = ["TYPE: CODING", "="*50, result.get('question', 'Text not extracted')]
    if result.get('images'): out.append(f"[Found {len(result['images'])} images in problem statement]")
    return "\n".join(out)
