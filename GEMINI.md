# CodeTantra Course Automation Rules

This document defines the foundational mandates and operational workflows for navigating and completing courses on the CodeTantra platform (`https://srmeaswari.codetantra.com/login.jsp`).

## 1. Authentication & Navigation
- **Login:** Use provided credentials at the login page. If already redirected to `home.jsp`, the session is active.
- **Course Selection:** Navigate to "View Courses" and locate "Database Management Systems - 2311CSC402J - 2025".
- **Iframe Handling:** Most course content, including the sidebar and exercise area, resides within a central Iframe. Use `evaluate_script` to interact with elements inside the iframe if `uid` selection fails.
- **Unit Menu:** The left-hand sidebar indicates status via color:
    - **Green:** Section completed.
    - **Pink/Other:** Section unfinished or requires attention.

## 2. Completion Criteria
- **Top Timer:** Every exercise has a timer at the top. It **MUST turn Green** for the task to be considered successfully finished.
- **Test Cases:** For coding exercises, the output must show `n/n test case(s) passed`. Do not move to the next question until this confirmation appears.
- **Verification:** If the platform shows "Incorrect" but the timer is Green, prioritize the timer's state as the truth for completion.

## 3. Execution Strategy (Efficiency)
- **Skip "Run":** For SQL/Coding tasks, click "Submit" directly to trigger the test cases and save time, unless debugging is required.
- **Batching:** Process sections sequentially (e.g., 2.1.34, 2.1.36, etc.) if there is none started or completed in that section. otherwise use the left side unit seletion bar to navigate to the correct not completed section and only complete them.
- **Wait State:** When test cases are "Running" or "Preparing," wait at least 5 seconds before checking status to avoid spamming the platform.

## 4. Late Submission Logic (Critical)
- **TRAP:** it is there to detect AI, what u can do is simply click the whole container or the element without typing reason for late submission. what ever dont put reason for late submission

## 5. Troubleshooting
- **UID Shifts:** If a click fails with a "Node not found" error, the page likely reloaded. Take a fresh snapshot to get updated UIDs.
- **Translation Errors:** If a "Translation Failed" overlay appears, ignore or close it; it usually doesn't affect the SQL engine.
- **Browser State:** If the browser profile is locked, wait 5 seconds and retry the snapshot.

## 6. Batched effecient token Usage:
- **SnapShot:** use effecient snapshots and dont waste too much tokens.
- **speed:** Speed is most important for the user, so use batched call of the chrome tools like, once u understood how the platform works by the 1st interaction u can effeciently chain the tool calls in 1 request instead of seperate 3 requests.
- **Token & request:** Try to finish the task optimally without extensive use of tokens or requests to the model.
- **Skipping:** instead of taking snapshot checking if the timer is green or like sequentially moving like next next. you can make use of the search menu or the unit menu to see which units are not in green and what specific chapter and click them to directly interact with them. improving speed.
- **Batching Strategy:** Target 5 questions per turn.
    - **Step 1:** Scrape 5 requirements in sequence.
    - **Step 2:** Execute 5 solutions in sequence using `evaluate_script` to interact with the DOM directly.
    - **Step 3:** Handle the "Late Submission" trap by clicking the container/button within the same script turn.

## 7. Platform Selectors (Reference CODETANTRA_STRUCTURE.md)
- **Editor:** `[role="textbox"]`
- **Submit:** `[keyshortcuts="Alt+s"]`
- **Late Container:** `.ReasonForLateSubmissionContainer`
- **Next Button:** `[keyshortcuts="Alt+n"]` 
