---
name: CodeTantra Sidebar Status Detection
description: How to detect completed vs unfinished questions in CodeTantra sidebar
type: reference
---

## CodeTantra Sidebar Status Indicators

### Sidebar SVG Classes (in iframe content)

Questions in the sidebar have SVG icons with specific CSS classes indicating status:

| Status | CSS Class | Color |
|--------|-----------|-------|
| **Completed** | `text-success` | Green (rgb(9, 190, 139)) |
| **In Progress** | `text-accent` | Purple/Pink (rgb(193, 73, 173)) |
| **Not Started** | (none/default) | Dark Blue/Gray (rgb(58, 78, 105)) |

### Detection Strategy

```javascript
// Find SVG in question button
const svg = btn.querySelector('svg');
const svgClass = (svg.className?.baseVal || svg.className || '').toString();

if (svgClass.includes('text-success')) {
    // COMPLETED - skip this question
} else if (svgClass.includes('text-accent')) {
    // IN PROGRESS - can work on this
} else {
    // NOT STARTED - work on this
}
```

### In-Question Timer Colors

Timer element: `.badge.badge-secondary.badge-sm`
- **Yellow/Amber** (`badge-warning`): Question in progress
- **Green**: Question completed

### Navigation Strategy

1. Navigate to course contents page
2. Scan all buttons with "Question" or "Exercise" in text
3. Check SVG class for each
4. Find first question that is NOT `text-success`
5. Click that question button
6. Detect if MCQ or Coding task
