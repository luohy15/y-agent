# y-agent desktop (Mac)

Electron shell for [yovy.app](https://yovy.app) plus a global `⌘⌃Y`
selection-to-prompt flow. macOS-only.

## Run

```bash
cd desktop
npm install
npm start
```

`npm install` pulls `electron`, `react`/`react-dom`, `vite`, and `typescript`.
`npm start` builds `src/main/**` via `tsc` (→ `dist/main/`, `dist/preload.js`)
and the renderer via `vite build` (→ `dist/renderer/`), then runs `electron .`,
which opens the main window (loads `https://yovy.app`) and registers the `⌘⌃Y`
shortcut.

Scripts:

| Script | What it does |
|---|---|
| `npm run build:main` | `tsc -p tsconfig.main.json` — compiles main + preload |
| `npm run build:renderer` | `vite build` — bundles the React prompt window |
| `npm run build` | Both of the above |
| `npm start` | `build` then `electron .` |
| `npm run dist` | `build` then `electron-builder --mac --dir` |

## Sign-in

Google's OAuth blocks embedded browsers (Electron, etc.) via the
"disallowed_useragent" policy, so sign-in happens in your real browser via a
loopback redirect:

1. On first launch (or any time the main window has no JWT), the app opens
   your default browser at `https://yovy.app/?auth_redirect=http://127.0.0.1:<port>/cb`.
2. You complete Google Sign-In there normally.
3. yovy.app redirects back to the loopback URL with the JWT in the query
   string. The Electron main process catches that request, injects the token
   into the main window's `localStorage`, and reloads.

The JWT persists across restarts in `localStorage`. If you ever click the
"Sign in with Google" button inside the main window, it routes through the
same loopback flow.

## macOS permissions

The selection-to-prompt feature drives keystrokes via AppleScript (`System
Events`), which macOS gates behind two privacy categories. Both prompts only
appear the first time we try to use the capability; if you tap "Don't Allow",
re-enable manually in **System Settings → Privacy & Security**.

| When you'll see the prompt | Category | What to grant |
|---|---|---|
| First `⌘⌃Y` after a fresh launch — when we run `osascript ... keystroke "c" using command down` to copy the current selection | **Automation** → "y-agent" wants to control "System Events" | Allow |
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
2. Press `⌘⌃Y` (Command+Control+Y).
3. Type an instruction in the small floating input.
4. `Enter` — paste the result back, replacing the selection in the original
   app.
5. `Shift+Enter` — copy the result to the clipboard and show a confirmation
   popup (no paste-back). Useful in read-only contexts.
6. `Esc` — dismiss without sending.

If you trigger the shortcut without a selection, the input still opens — you
can use it as a quick prompt that copies the result to the clipboard.

## Troubleshooting

- **Stuck on sign-in**: if the browser tab didn't open automatically, click
  the "Sign in with Google" button in the main window — it will retrigger the
  loopback flow. If port `127.0.0.1:<random>` can't bind, check whether a
  local firewall/VPN is blocking loopback.
- **Selection comes back empty**: the source app may have a slow Cmd+C
  pipeline (Word, certain web editors, Terminal, VSCode diff). The capture
  window is 1000ms; raise `CLIPBOARD_POLL_TIMEOUT_MS` in `constants.ts` if
  your app is slower. We also wait `PRE_KEYSTROKE_DELAY_MS` (~120ms) before
  firing Cmd+C so chord modifiers can release, and retry once after
  `RETRY_DELAY_MS` (~200ms) if the first pass is empty — bump these if your
  hand-release is unusually slow.
- **Paste-back lands in the wrong app**: macOS sometimes refuses to refocus a
  background app within 80ms. Increase the `sleep(80)` in `handleSelectionShortcut`'s
  paste branch, or use `Shift+Enter` and paste manually.
- **`⌘⌃Y` doesn't fire**: another app may have grabbed the shortcut first.
  Rebind via `SELECTION_SHORTCUTS` in `constants.ts`. Avoid bare Option-letter
  combos like `⌥N` — they're macOS dead-keys and our synthesized `⌘C` lands
  while the source app is in compose-state, breaking selection capture.

## Files

```
src/
├── main/
│   ├── index.ts        app lifecycle, global shortcut wiring, UA spoof
│   ├── constants.ts    APP_URL, shortcut accelerators, polling timings
│   ├── paths.ts        runtime paths for preload / renderer / icon
│   ├── state.ts        shared mainWindow / promptWindow / lastSelection
│   ├── windows.ts      createMainWindow / createPromptWindow / showPromptWindow
│   ├── selection.ts    AppleScript ⌘C capture + TCC permission notice
│   ├── oauth.ts        loopback OAuth server + ensureLoggedInViaBrowser
│   ├── inline-api.ts   JWT read + POST /api/inline
│   └── ipc.ts          ipcMain handlers (submit / copy / resize / close)
├── preload.ts          contextBridge `window.api` surface
└── renderer/
    ├── index.html      Vite entry
    ├── main.tsx        React root
    ├── App.tsx         prompt window (input + result phases)
    ├── styles.css      ported from prompt-window.html
    └── global.d.ts     `window.api` type
```

Build outputs land in `dist/` (gitignored). `electron-builder` ships
`dist/**`, `icon.png`, and `icon.icns`.

This is the MVP scope from `pages/plan-1981-mac-desktop.md` §9. Tray, screenshot,
local notifications, Keychain JWT, deep links, and DMG packaging are all
deferred to Phase 1.
