import { clipboard, dialog, shell } from 'electron';
import { exec } from 'child_process';
import { promisify } from 'util';
import { state } from './state';
import { CLIPBOARD_POLL_INTERVAL_MS, CLIPBOARD_POLL_TIMEOUT_MS } from './constants';

const execAsync = promisify(exec);
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

type PermissionKind = 'automation' | 'accessibility';

// Once we've nagged the user about a given permission category, don't re-prompt
// during the same session — the system-settings shortcut already opened the
// pane and re-popping a sheet on every keystroke is worse than the underlying
// failure.
const permissionNoticeShown: Record<PermissionKind, boolean> = {
  automation: false,
  accessibility: false,
};

// Detect AppleScript / TCC denial from osascript stderr.
//   -1743 / "not allowed sending events" / "not authorized" — Automation
//   -25006 / -25007 / "assistive access" / "accessibility" — Accessibility
//   1002  / "not allowed to send keystrokes"               — Accessibility
//     (System Events keystroke synthesis is gated by Accessibility on
//     macOS 13+; the textual message varies by OS version.)
function classifyPermissionError(err: unknown): PermissionKind | null {
  const e = err as { stderr?: string; message?: string } | null;
  const msg = String((e && (e.stderr || e.message)) || '');
  if (/-1743|not authorized|not allowed sending events/i.test(msg)) return 'automation';
  if (/-25006|-25007|assistive access|accessibility|not allowed to send keystrokes|\(1002\)/i.test(msg)) return 'accessibility';
  return null;
}

// Trigger ⌘C in the frontmost app, read whatever lands on the clipboard, then
// restore the user's previous clipboard contents. Returns the captured text
// (empty string if nothing was selected / Cmd+C didn't produce text).
export async function captureSelection(): Promise<string> {
  const previousText = clipboard.readText();
  // Clear so we can unambiguously detect Cmd+C landing, even if the selection
  // happens to equal the previous clipboard text.
  clipboard.clear();

  try {
    await execAsync(
      'osascript -e \'tell application "System Events" to keystroke "c" using command down\'',
    );
  } catch (err) {
    console.error('[selection] AppleScript Cmd+C failed:', (err as Error).message);
    if (previousText) clipboard.writeText(previousText);
    showPermissionNotice(classifyPermissionError(err));
    return '';
  }

  let captured = '';
  const start = Date.now();
  while (Date.now() - start < CLIPBOARD_POLL_TIMEOUT_MS) {
    await sleep(CLIPBOARD_POLL_INTERVAL_MS);
    const current = clipboard.readText();
    if (current) {
      captured = current;
      break;
    }
  }

  if (previousText) clipboard.writeText(previousText);
  return captured;
}

// Surface a permission-related AppleScript failure as a sheet over the main
// window with a one-click jump to the relevant System Settings pane. Idempotent
// per session per category so we don't spam the user mid-flow.
function showPermissionNotice(kind: PermissionKind | null): void {
  if (!kind || permissionNoticeShown[kind]) return;
  permissionNoticeShown[kind] = true;

  const isAutomation = kind === 'automation';
  const title = isAutomation
    ? 'Automation permission needed'
    : 'Accessibility permission needed';
  const detail = isAutomation
    ? 'y-agent uses AppleScript to copy your selection (⌘C) and paste the result back (⌘V). macOS just blocked that.\n\nGrant access under System Settings → Privacy & Security → Automation, then enable "System Events" under y-agent.'
    : 'y-agent needs Accessibility access to synthesize keystrokes for selection capture and paste-back.\n\nGrant access under System Settings → Privacy & Security → Accessibility and toggle y-agent on.';
  const settingsUrl = isAutomation
    ? 'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation'
    : 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility';

  const opts = {
    type: 'warning' as const,
    buttons: ['Open System Settings', 'Later'],
    defaultId: 0,
    cancelId: 1,
    title,
    message: title,
    detail,
  };

  const { mainWindow } = state;
  const promise = mainWindow && !mainWindow.isDestroyed()
    ? dialog.showMessageBox(mainWindow, opts)
    : dialog.showMessageBox(opts);

  promise
    .then(({ response }) => {
      if (response === 0) shell.openExternal(settingsUrl);
    })
    .catch((err: Error) => console.error('[perms] dialog failed:', err.message));
}
