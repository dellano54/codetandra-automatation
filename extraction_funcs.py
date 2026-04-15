"""
Extraction functions for CodeTantra questions.
Handles MCQ and Coding question content extraction from the iframe.
"""
import asyncio


async def extract_mcq_content(frame):
    """
    Extract MCQ question content and options from the frame.
    Returns a dictionary with question text and options.
    """
    js_code = r"""
    () => {
        try {
            // Try multiple selectors for the question text
            const questionSelectors = [
                '.question-text',
                '.question-content',
                '.mcq-question',
                '[class*="question"]',
                'h4',
                '.problem-statement'
            ];

            let questionText = '';
            for (const selector of questionSelectors) {
                const el = document.querySelector(selector);
                if (el && el.innerText.trim().length > 10) {
                    if (!el.querySelector('input[type="radio"]')) {
                        questionText = el.innerText.trim();
                        break;
                    }
                }
            }

            // If no specific question element found, try to get text before options
            if (!questionText) {
                const allText = document.body.innerText;
                const radioIndex = allText.indexOf('A.');
                if (radioIndex > 50) {
                    questionText = allText.substring(0, radioIndex).trim();
                }
            }

            // Clean up the question text
            if (questionText) {
                const noise = ['Submit', 'Prev', 'Next', 'Reset', 'Reason for late submission', 'Please enter at least 15 characters'];
                noise.forEach(n => {
                    questionText = questionText.replace(new RegExp(n, 'gi'), '');
                });
                questionText = questionText.trim();
            }

            // Extract options
            const options = [];
            const radioInputs = document.querySelectorAll('input[type="radio"]');

            radioInputs.forEach((input, index) => {
                const label = input.closest('label');
                const parent = label || input.parentElement;
                if (parent) {
                    let optionText = parent.innerText.trim();
                    optionText = optionText.replace(new RegExp('^\\s*[\\u25cb\\u25c9\\u25ef]?\\s*'), '');
                    if (optionText) {
                        options.push({
                            letter: String.fromCharCode(65 + index),
                            text: optionText
                        });
                    }
                }
            });

            // Alternative: try finding by label with 'for' attribute
            if (options.length === 0) {
                const labels = document.querySelectorAll('label');
                let optIndex = 0;
                labels.forEach(label => {
                    const text = label.innerText.trim();
                    if (text && text.length > 0 && !text.includes('Submit')) {
                        options.push({
                            letter: String.fromCharCode(65 + optIndex),
                            text: text.replace(new RegExp('^\\s*[\\u25cb\\u25c9\\u25ef]?\\s*'), '')
                        });
                        optIndex++;
                    }
                });
            }

            return {
                question: questionText || 'Content not found',
                options: options
            };
        } catch (e) {
            return { question: 'Error: ' + e.message, options: [] };
        }
    }
    """

    result = await frame.evaluate(js_code)
    return result


async def extract_coding_content(frame):
    """
    Extract coding question content from the frame.
    Returns a dictionary with question text, code template, and test cases.
    """
    js_code = r"""
    () => {
        try {
            // Try to find the problem statement with more specific selectors
            const problemSelectors = [
                '.problem-statement',
                '.coding-question',
                '.question-text',
                '[class*="question-content"]',
                '[class*="exercise"]',
                '.content-area',
                '[role="main"]'
            ];

            let problemText = '';
            for (const selector of problemSelectors) {
                const el = document.querySelector(selector);
                if (el && el.innerText.trim().length > 50) {
                    const text = el.innerText.trim();
                    // Make sure it doesn't look like code/script
                    if (!text.includes('function') || text.includes('Table')) {
                        problemText = text;
                        break;
                    }
                }
            }

            // If not found, try to find text between sidebar and editor
            if (!problemText) {
                const allDivs = document.querySelectorAll('div, article, section');
                for (const div of allDivs) {
                    const text = div.innerText || '';
                    if (text.length > 200 && text.length < 5000 &&
                        (text.includes('Table') || text.includes('Write a') || text.includes('Query') ||
                         text.includes('employee') || text.includes('product') || text.includes('department'))) {
                        if (!text.includes('function opendialog') &&
                            !text.includes('window.MathJax') &&
                            !text.includes('window.addEventListener') &&
                            !text.includes('localStorage')) {
                            problemText = text;
                            break;
                        }
                    }
                }
            }

            // Clean up problem text by removing navigation elements
            if (problemText) {
                // Remove common navigation patterns
                const navPatterns = [
                    /Pin\s*Search course\s*ctrl\+k[^]*?Close/,
                    /\d+\.\s*Unit \d+[^]*?Unit \d+[^]*?\d+\.\d+\.\s*/,
                    /Minimum \d+ characters required for search/,
                    /Database Management Systems[^]*?\d+:\d+/,
                    /Explorer\s*index\.sql/
                ];

                navPatterns.forEach(pattern => {
                    problemText = problemText.replace(pattern, '');
                });

                // Remove the numbered list of units (4.1, 4.2, etc.)
                problemText = problemText.replace(/\d+\.\d+\.\s*[^\n]+\n/g, '');
                problemText = problemText.replace(/\d+\.\s*Unit[^\n]+\n/g, '');

                // Clean up extra whitespace
                problemText = problemText.replace(/\n{3,}/g, '\n\n');
            }

            // Last resort: try to get from body but filter heavily
            if (!problemText) {
                const paragraphs = document.querySelectorAll('p');
                const contentParts = [];
                for (const p of paragraphs) {
                    const text = p.innerText.trim();
                    if (text.length > 20 &&
                        !text.includes('function') &&
                        !text.includes('Unit') &&
                        !text.includes('Sidebar')) {
                        contentParts.push(text);
                    }
                }
                if (contentParts.length > 0) {
                    problemText = contentParts.join('\n\n');
                }
            }

            // Clean up the problem text
            if (problemText) {
                const stopMarkers = ['Write your query', 'Code Template:', 'Editor', 'Submit', 'Prev', 'Next'];
                for (const marker of stopMarkers) {
                    const idx = problemText.indexOf(marker);
                    if (idx > 100) {
                        problemText = problemText.substring(0, idx);
                    }
                }

                const noise = ['Reason for late submission', 'Please enter at least 15 characters'];
                noise.forEach(n => {
                    problemText = problemText.replace(new RegExp(n, 'gi'), '');
                });

                problemText = problemText.trim();
            }

            // Look for code editor content
            let codeTemplate = '';
            const editorSelectors = [
                '.cm-content',
                '.CodeMirror-code',
                'textarea',
                '[role="textbox"]'
            ];

            for (const selector of editorSelectors) {
                const el = document.querySelector(selector);
                if (el && el.value) {
                    codeTemplate = el.value;
                    break;
                } else if (el && el.innerText) {
                    codeTemplate = el.innerText;
                    break;
                }
            }

            // Extract test cases info
            let testCases = '';
            const testSelectors = ['.test-cases', '.test-case', '[class*="test"]'];
            for (const selector of testSelectors) {
                const el = document.querySelector(selector);
                if (el) {
                    testCases = el.innerText.trim();
                    break;
                }
            }

            return {
                question: problemText || 'Coding problem content not found',
                codeTemplate: codeTemplate,
                testCases: testCases
            };
        } catch (e) {
            return { question: 'Error: ' + e.message, codeTemplate: '', testCases: '' };
        }
    }
    """

    result = await frame.evaluate(js_code)
    return result


async def wait_for_question_load(frame, timeout=15):
    """
    Wait for the question content to load in the frame.
    Returns True if loaded, False if timeout.
    """
    js_code = r"""
    () => {
        const hasMCQ = document.querySelectorAll('input[type="radio"]').length >= 2;
        const hasCoding = !!document.querySelector('.cm-content, [role="textbox"], .CodeMirror');
        const hasQuestion = !!document.querySelector('.question-text, .problem-statement, h4, .question-content');
        return (hasMCQ || hasCoding || hasQuestion);
    }
    """

    for _ in range(timeout):
        loaded = await frame.evaluate(js_code)
        if loaded:
            return True
        await asyncio.sleep(1)

    return False


def format_mcq_output(extraction_result):
    """Format MCQ extraction result for display."""
    if not extraction_result:
        return "Extraction failed: No result"

    output = []
    output.append("=" * 50)
    output.append("TYPE: MCQ")
    output.append("=" * 50)
    output.append(f"\nQuestion:\n{extraction_result.get('question', 'Not found')}")

    options = extraction_result.get('options', [])
    if options:
        output.append("\nOptions:")
        for opt in options:
            output.append(f"  {opt['letter']}. {opt['text']}")
    else:
        output.append("\nOptions: None found")

    return "\n".join(output)


def format_coding_output(extraction_result):
    """Format Coding extraction result for display."""
    if not extraction_result:
        return "Extraction failed: No result"

    output = []
    output.append("=" * 50)
    output.append("TYPE: CODING")
    output.append("=" * 50)
    output.append(f"\nProblem:\n{extraction_result.get('question', 'Not found')}")

    code = extraction_result.get('codeTemplate', '')
    if code:
        output.append(f"\nCode Template:\n{'-' * 30}\n{code}\n{'-' * 30}")

    tests = extraction_result.get('testCases', '')
    if tests:
        output.append(f"\nTest Cases:\n{tests}")

    return "\n".join(output)
