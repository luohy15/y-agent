# y-agent desktop (Mac)

Electron shell for [yovy.app](https://yovy.app) plus a global `Alt+Space`
selection-to-prompt flow. macOS-only.

## Run

```bash
cd desktop
npm install
npm start
```

`npm install` will pull `electron`. `npm start` runs `electron .`, which opens
the main window (loads `https://yovy.app`) and registers the `Alt+Space`
shortcut.

The web app's `localStorage` is reused for sign-in — log in once via Google
OAuth in the main window and the JWT persists across restarts.

## macOS permissions

The selection-to-prompt feature drives keystrokes via AppleScript (`System
Events`), which macOS gates behind two privacy categories. Both prompts only
appear the first time we try to use the capability; if you tap "Don't Allow",
re-enable manually in **System Settings → Privacy & Security**.

| When you'll see the prompt | Category | What to grant |
|---|---|---|
| First `Alt+Space` after a fresh launch — when we run `osascript ... keystroke "c" using command down` to copy the current selection | **Automation** → "y-agent" wants to control "System Events" | Allow |
| When the result is pasted back via `keystroke "v" using command down` | **Accessibility** (only required if macOS escalates from Automation; some macOS versions ask once, others ask both) | Add y-agent (or your terminal/Electron during dev) and toggle on |

If a permission-related error occurs at runtime, the app pops a sheet over the
main window with a "Open System Settings" shortcut that takes you straight to
the relevant pane.

### Granting / revoking manually

- Automation: System Settings → Privacy & Security → **Automation** → expand
  the "y-agent" entry → toggle **System Events** on.
- Accessibility: System Settings → Privacy & Security → **Accessibility** →
  add y-agent (or your dev shell, e.g. `/Applications/Electron.app`) and toggle
  it on.

To force the system prompts again during development, reset the categories for
y-agent and re-trigger the shortcut:

```bash
tccutil reset AppleEvents
tccutil reset Accessibility
```

`tccutil reset <category> <bundle-id>` is more surgical if you only want to
reset y-agent without affecting other apps.

## Usage

1. Select text in any app.
2. Press `Alt+Space` (i.e. `⌥Space`).
3. Type an instruction in the small floating input.
4. `Enter` — paste the result back, replacing the selection in the original
   app.
5. `Shift+Enter` — copy the result to the clipboard and show a confirmation
   popup (no paste-back). Useful in read-only contexts.
6. `Esc` — dismiss without sending.

If you trigger the shortcut without a selection, the input still opens — you
can use it as a quick prompt that copies the result to the clipboard.

## Troubleshooting

- **Google OAuth fails with "browser not supported"**: the shell already strips
  `Electron/...` from the User-Agent. If you still hit it, try a full restart;
  Google sometimes caches the rejected UA per session.
- **Selection comes back empty**: the source app may have a slow Cmd+C
  pipeline (Word, certain web editors). The capture window is 300ms; raise
  `CLIPBOARD_POLL_TIMEOUT_MS` in `main.js` if your app is slower.
- **Paste-back lands in the wrong app**: macOS sometimes refuses to refocus a
  background app within 80ms. Increase the `sleep(80)` in `handleSelectionShortcut`'s
  paste branch, or use `Shift+Enter` and paste manually.
- **`Alt+Space` doesn't fire**: another app (Spotlight on some setups,
  third-party launchers) may have grabbed the shortcut first. Rebind by
  changing `SELECTION_SHORTCUT` in `main.js`.

## Files

- `main.js` — Electron main process. Window creation, UA spoof, global
  shortcut, AppleScript invocation, IPC handlers, permission-error detection.
- `preload.js` — `contextBridge` surface used by the prompt + result windows.
- `prompt-window.html` — frameless 480×100 input popover.
- `result-popup.html` — non-focusable confirmation popup for `Shift+Enter`.
- `package.json` — single dep: `electron`.

This is the MVP scope from `pages/plan-1981-mac-desktop.md` §9. Tray, screenshot,
local notifications, Keychain JWT, deep links, and DMG packaging are all
deferred to Phase 1.
