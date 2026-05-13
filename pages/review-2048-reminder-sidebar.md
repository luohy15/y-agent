---
title: review for todo 2048 — reminder sidebar add/edit/delete
type: review
verdict: approve
---

## Verdict
approve

## Plan adherence

Spec is the todo desc (no separate plan note). All required operations land:

- **Add**: '+' button in header opens modal form with `title` (required), `remind_at` datetime-local picker (defaults to +60min), `description`, optional `todo_id` / `calendar_event_id`. POSTs to `/api/reminder`. ✓
- **Edit**: clicking a row opens the same modal prefilled via `formFromReminder`; saves via `/api/reminder/update`. ✓
- **Delete**: trash icon on row hover and Delete button inside edit modal; both go through `window.confirm()` and POST `/api/reminder/delete`. ✓
- **List view**: status filter pills (pending / sent / cancelled / all, persisted to `localStorage`), status badge rendered for non-pending rows, time per row, grouped by day, sorted by `remind_at`. ✓

Recurrence and chat association from the desc are correctly skipped — the data model (`storage/entity/reminder.py`) has no recurrence column and no chat FK, so the desc's "if existing data model supports it" clause applies.

Empty / loading / error states all handled (sign in prompt, "Loading reminders...", "Error loading reminders", "No reminders").

CRUD was tested end-to-end against prod per the todo progress note.

## Findings (request-changes)

None.

## Suggestions (nit, non-blocking)

- **Empty-string vs null on update** (`ReminderList.tsx:230-241`): when the user clears `description` / `todo_id` / `calendar_event_id` in edit mode, the frontend always sends those fields as `""` (after `.trim()`). The API only filters out `None`, so the service writes `""` into the row instead of `NULL`. Create path correctly omits empty fields; update path is asymmetric. Cosmetic only — the read path uses `r.todo_id || ""`, so display is unaffected — but it leaks empty strings into the DB. If you want consistency, omit empty values from the update body too.
- **Past `remind_at`**: the picker accepts past datetimes; the backend will happily store one and the scheduler will fire on next tick. Not a blocker (CLI has the same behavior) but a `min` attribute or a soft warning would be nice.
- **Form title used in delete confirm** (`ReminderList.tsx:439`): the delete button inside the edit modal builds the confirm prompt from `form.title` (the possibly-edited, unsaved title) rather than the original reminder title. Minor — the user sees what they typed, not what's stored. Cheap fix: capture the original title when opening edit.
- **Inline `vite.config.ts` ngrok host**: harmless but the allowed-hosts list keeps growing. Worth a follow-up to swap to a wildcard or env var.
