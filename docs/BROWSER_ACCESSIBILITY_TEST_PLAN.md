# Browser and Accessibility Test Plan

## Purpose and limits

This plan covers the Grievance Portal's public pages and authenticated complainant/authority workflows. It is a repeatable manual browser checklist plus lightweight source-level regression checks that use Python's standard library and the project's existing Flask test setup. It is not a WCAG conformance claim.

## Pages and critical flows

Test these pages as the relevant role permits:

- Home and navigation: `/`
- Registration and login: `/register`, `/login`
- Complaint submission and confirmation: `/complaint`
- Case tracking: `/track`
- Complainant case list, case details, and messaging: `/my-complaints`, `/my-complaints/<case_id>`
- Authority dashboard filters/pagination, reports, verification review, case status/priority updates, messaging, and identity-disclosure form: `/authority/dashboard`, `/authority/reports`, `/authority/verifications`, `/authority/case/<case_id>`
- Notifications and read actions: `/notifications`
- Identity verification: `/verification`
- Error/empty states and logout

Use test accounts and synthetic cases only. Do not use real complainant identity data for accessibility testing.

## Browser and viewport matrix

Run the same key flows in the latest supported Chromium-based browser and Firefox. If available, include Safari because native form controls and VoiceOver are relevant. Record browser/version, OS, viewport, role, test data, outcome, and a screenshot for every failure.

| Viewport | What to inspect |
| --- | --- |
| 320 × 800 | Narrow mobile: no horizontal page overflow, clipped controls, or hidden actions; navigation wraps; tables and case cards remain usable. |
| 375 × 812 | Typical mobile: complaint form, error text, buttons, status badges, and message history fit and remain readable. |
| 768 × 1024 | Tablet: dashboard filters, cards, tables, pagination, and verification forms reflow. |
| 1024 × 768 | Small desktop/tablet landscape: dashboard and report grids do not overlap. |
| 1440 × 900 | Desktop: sensible content width, readable line length, and consistent spacing. |
| 200% browser zoom | No lost content or functionality; keyboard focus is not hidden behind sticky/navigation elements. |

At each width, inspect Home, Login, Registration, Complaint, Track, My Complaints, Case Details, Notifications, Authority Dashboard, Authority Case, Verification, and Reports. If a page is role-gated, use its proper test account.

## Keyboard-only pass

Use the keyboard only; do not use a mouse/trackpad.

1. Load the page and press Tab from the browser chrome into page content. Confirm focus is visible and follows a logical reading/action order.
2. Use Shift+Tab to reverse direction; ensure focus is never lost or trapped.
3. Activate links with Enter and buttons with Enter/Space as appropriate.
4. Operate selects, checkboxes, radio groups, date inputs, pagination, filters, and status controls with keyboard keys.
5. Complete login, registration, complaint submission, tracking, a message, verification request/review, notification read, and logout.
6. Confirm every action is keyboard reachable and no hover-only action is required.
7. Confirm dialogs/errors do not steal focus unexpectedly; after a failed submission, locate the error and the field requiring correction.
8. Check that focus indicators remain visible against both light and dark navigation backgrounds.

**Pass criterion:** every interactive action is reachable and operable by keyboard; focus is always visible, logical, and not obscured. Record any exception with page, element, and reproduction steps.

## Form labels, instructions, and errors

For every form:

- Every text input, select, radio group, checkbox, date input, and textarea has a programmatic accessible name. A placeholder alone is not a label.
- Labels are clickable and associated with the intended field; grouped radio options use an appropriate group label/legend.
- Required fields are identified in text and with the native `required` attribute where appropriate.
- Input purpose, format, and limits are explained before submission where needed.
- Submit an empty form, malformed email/phone, invalid date, invalid case ID, and too-long message where applicable.
- Errors are written in plain language, associated with the affected field where possible, and announced to assistive technology. Do not communicate errors by color alone.
- After validation fails, entered data is preserved where appropriate and the user can find and correct the problem.
- Success confirmations, status updates, and notification changes are announced or discoverable without relying only on visual position.

## Contrast and visual presentation

Check normal text against its actual background, including links, placeholders, muted metadata, status badges, alerts, button text, table headers, navigation, focus indicators, and disabled states.

- Target WCAG 2.2 AA contrast: at least 4.5:1 for normal text and 3:1 for large text.
- Check meaningful UI boundaries, icons, and focus indicators against adjacent colors (target 3:1).
- Do not rely on red/green alone to communicate status.
- Test Windows high-contrast/forced-colors mode if available.
- Use a contrast analyzer or browser accessibility tooling for measured ratios; visual judgment alone is not sufficient.

## Screen reader and semantic structure

Perform a real assistive-technology pass where available:

- Windows: NVDA with Firefox or Chromium.
- macOS/iOS: VoiceOver with Safari.
- Android: TalkBack with Chrome.

Verify page title, language, heading hierarchy, navigation/main landmarks, link and button names, form labels, table header relationships, list structure, alert/error announcements, status updates, and reading order. Confirm that repeated navigation links can be distinguished by their context and that pagination has a label. Check that buttons describe their action rather than only their appearance.

Inspect complaint and message content containing punctuation, long IDs, and multiline text. Check dynamic category changes on the complaint form: the updated instructions/options should be announced or otherwise discoverable, and focus must not unexpectedly move.

## Existing automated checks

Run locally:

```bash
python -m compileall -q app.py tests
python -m unittest discover -s tests -t .
```

The added source-level checks cover responsive viewport metadata, visible-focus CSS, labels for key message/status controls, and accessible error roles. Existing tests cover form CSRF tokens and application workflows. These checks do not render CSS or simulate a browser.

## Manual-only checks and evidence

Unless a real browser, contrast analyzer, and assistive technology are actually run, mark these as **Not run** rather than Pass:

- Pixel/layout overflow at each viewport and at 200% zoom.
- Actual keyboard tab order, focus visibility/obscuring, and browser-native validation behavior.
- Measured contrast ratios for computed foreground/background pairs.
- Screen-reader announcement quality and landmark/heading navigation.
- Dynamic DOM behavior of the complaint form and any JavaScript-generated content.
- Touch target size, mobile browser behavior, and orientation changes.

Record each check as Pass / Fail / Not run with environment and evidence. Automated source tests are supporting evidence, not a substitute for these manual checks.
