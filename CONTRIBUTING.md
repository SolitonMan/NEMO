## Accessibility Standards
- All templates must meet WCAG 2.2 Level AA
- Key requirements: alt text, ARIA labels, keyboard navigation, 4.5:1 contrast
- Skip links required on all base templates

## Code Change Guidelines
- Show only specific lines that need to change, not entire files
- Include clear context about line numbers or surrounding code
- Never regenerate complete files unless explicitly requested
- Make changes easy to review and apply

## Character Encoding Standards
- **All code must use only ASCII characters (characters 0-127)**
- No Unicode characters allowed in code (e.g., no ?, —, •, etc.)
- Use standard ASCII alternatives: hyphen (-) instead of em dash, asterisk (*) instead of bullet, etc.
- Comments, strings, and all code content must be pure ASCII