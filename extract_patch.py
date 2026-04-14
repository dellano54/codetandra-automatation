async def extract_mcq_content(page):
    """Extract MCQ question text and options"""
    result = await page.evaluate(r"""() => {
        const iframe = document.querySelector('iframe');
        if (!iframe || !iframe.contentDocument) return { error: 'No iframe found' };
        const doc = iframe.contentDocument;

        // Extract question ID (from URL)
        let questionId = '';
        const urlMatch = iframe.src.match(/[?&]questionId=([^&]+)/);
        if (urlMatch) questionId = urlMatch[1];

        // Find the main question area (not sidebar)
        // Look for common question container patterns
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
            if (el && el.textContent.trim()) {
                questionText = el.textContent.trim();
                break;
            }
        }

        // If still no text, try to find the first substantial paragraph in question area
        if (!questionText && questionArea) {
            const paras = questionArea.querySelectorAll('p');
            for (const p of paras) {
                const text = p.textContent.trim();
                if (text.length > 30) {
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
            // Check if this is likely an MCQ option (parent contains option-like text)
            const parent = r.closest('label, div, li');
            if (!parent) return false;
            const text = parent.textContent.trim();
            // Skip sidebar items (they have pattern like 1.1.1)
            return text.length > 5 && text.length < 400 && !text.match(/^\d+\.\d+\.\d+/);
        });

        if (validRadios.length > 0 && validRadios.length <= 6) {
            validRadios.forEach((radio, idx) => {
                const container = radio.closest('label, div, li');
                if (!container) return;

                let text = container.textContent.trim();

                // Remove radio button text if present
                text = text.replace(/^\s*\u2713?\s*/, '').trim();

                // Look for option letter
                let label = String.fromCharCode(65 + idx); // Default A, B, C...
                const labelMatch = text.match(/^([A-D])[.)]?\s*/);
                if (labelMatch) {
                    label = labelMatch[1];
                    text = text.replace(labelMatch[0], '').trim();
                }

                if (text.length > 0 && text.length < 400) {
                    options.push({ id: label, text: text.substring(0, 300) });
                }
            });
        }

        // Strategy 2: Look for option containers
        if (options.length === 0 || options.length > 6) {
            const optionContainers = optionsRoot.querySelectorAll(
                '[class*="option-item"], [class*="option-container"]:not([class*="sidebar"]), .mcq-option'
            );

            if (optionContainers.length > 0 && optionContainers.length <= 6) {
                options.length = 0; // Clear any bad results
                optionContainers.forEach((container, idx) => {
                    const text = container.textContent.trim();
                    // Skip sidebar items
                    if (text.match(/^\d+\.\d+\.\d+/)) return;
                    if (text.length < 5 || text.length > 400) return;

                    let label = String.fromCharCode(65 + idx);
                    const labelMatch = text.match(/^([A-D])[.)]?\s*/);
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
