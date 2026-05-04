const { app, BrowserWindow, clipboard, dialog, globalShortcut, ipcMain, shell, net } = require('electron');
const path = require('path');
const { exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

// Once we've nagged the user about a given permission category, don't re-prompt
// during the same session — the system-settings shortcut already opened the
// pane and re-popping a sheet on every keystroke is worse than the underlying
// failure.
const permissionNoticeShown = { automation: false, accessibility: false };

// Detect AppleScript / TCC denial from osascript stderr. -1743 is "user denied
// authorization", -25006/-25007 are accessibility refusals, "not allowed" /
// "not authorized" / "assistive access" are the textual variants seen across
// macOS versions.
function classifyPermissionError(err) {
  const msg = String((err && (err.stderr || err.message)) || '');
  if (/-1743|not authorized|not allowed sending events/i.test(msg)) return 'automation';
  if (/-25006|-25007|assistive access|accessibility/i.test(msg)) return 'accessibility';
  return null;
}

const APP_URL = 'https://yovy.app';
const SELECTION_SHORTCUT = 'Alt+Space';
const CLIPBOARD_POLL_TIMEOUT_MS = 300;
const CLIPBOARD_POLL_INTERVAL_MS = 20;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let mainWindow = null;
let promptWindow = null;
let resultWindow = null;
let lastSelection = '';
// Name of the app frontmost at the moment the global shortcut fired. Used to
// re-activate that app before pasting back, since hiding our prompt window does
// not on its own restore focus to the previous app.
let lastFrontmostApp = null;

// Trigger ⌘C in the frontmost app, read whatever lands on the clipboard, then
// restore the user's previous clipboard contents. Returns the captured text
// (empty string if nothing was selected / Cmd+C didn't produce text).
async function captureSelection() {
  const previousText = clipboard.readText();
  // Clear so we can unambiguously detect Cmd+C landing, even if the selection
  // happens to equal the previous clipboard text.
  clipboard.clear();

  try {
    await execAsync(
      'osascript -e \'tell application "System Events" to keystroke "c" using command down\'',
    );
  } catch (err) {
    console.error('[selection] AppleScript Cmd+C failed:', err.message);
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

function createPromptWindow() {
  promptWindow = new BrowserWindow({
    width: 480,
    height: 100,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  promptWindow.loadFile(path.join(__dirname, 'prompt-window.html'));
  promptWindow.on('blur', () => promptWindow && promptWindow.hide());
  promptWindow.on('closed', () => { promptWindow = null; });
}

function showPromptWindow(selection) {
  if (!promptWindow) createPromptWindow();
  lastSelection = selection;
  const send = () => {
    promptWindow.webContents.send('prompt:init', { selection });
    promptWindow.show();
    promptWindow.focus();
  };
  if (promptWindow.webContents.isLoading()) {
    promptWindow.webContents.once('did-finish-load', send);
  } else {
    send();
  }
}

// Ask System Events which process is frontmost. Done before showing the prompt
// window so we know where to paste back to. Returns null on failure or when the
// frontmost app is our own Electron shell.
async function getFrontmostApp() {
  try {
    const { stdout } = await execAsync(
      'osascript -e \'tell application "System Events" to name of first application process whose frontmost is true\'',
    );
    const name = stdout.trim();
    if (!name) return null;
    if (/electron|y-agent/i.test(name)) return null;
    return name;
  } catch (err) {
    console.error('[selection] frontmost-app probe failed:', err.message);
    return null;
  }
}

// Surface a permission-related AppleScript failure as a sheet over the main
// window with a one-click jump to the relevant System Settings pane. Idempotent
// per session per category so we don't spam the user mid-flow.
function showPermissionNotice(kind) {
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
    type: 'warning',
    buttons: ['Open System Settings', 'Later'],
    defaultId: 0,
    cancelId: 1,
    title,
    message: title,
    detail,
  };

  const promise = mainWindow && !mainWindow.isDestroyed()
    ? dialog.showMessageBox(mainWindow, opts)
    : dialog.showMessageBox(opts);

  promise.then(({ response }) => {
    if (response === 0) shell.openExternal(settingsUrl);
  }).catch((err) => console.error('[perms] dialog failed:', err.message));
}

async function activateApp(name) {
  if (!name) return;
  const escaped = name.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  try {
    await execAsync(`osascript -e 'tell application "${escaped}" to activate'`);
  } catch (err) {
    console.error('[paste] activate failed:', err.message);
  }
}

async function pasteViaCmdV() {
  try {
    await execAsync(
      'osascript -e \'tell application "System Events" to keystroke "v" using command down\'',
    );
  } catch (err) {
    console.error('[paste] AppleScript Cmd+V failed:', err.message);
    showPermissionNotice(classifyPermissionError(err));
    throw err;
  }
}

async function handleSelectionShortcut() {
  try {
    // Record the previously-focused app BEFORE we capture (Cmd+C also runs
    // against the frontmost app, so this reads the one the user actually meant).
    lastFrontmostApp = await getFrontmostApp();
    const selection = await captureSelection();
    showPromptWindow(selection);
  } catch (err) {
    console.error('[selection] capture failed:', err);
  }
}

// Read the JWT that the web app stores in localStorage on the main window. The
// prompt window is a separate BrowserWindow without access to that storage, so
// the main process pulls the token on demand via executeJavaScript.
async function getJwtFromMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return null;
  try {
    return await mainWindow.webContents.executeJavaScript('localStorage.getItem("jwt_token")');
  } catch (err) {
    console.error('[inline] failed to read jwt_token:', err.message);
    return null;
  }
}

async function callInlineApi(selection, instruction) {
  const token = await getJwtFromMainWindow();
  if (!token) throw new Error('not signed in (no jwt_token on main window)');

  const body = JSON.stringify({ selection, instruction });
  return new Promise((resolve, reject) => {
    const req = net.request({ method: 'POST', url: `${APP_URL}/api/inline` });
    req.setHeader('Content-Type', 'application/json');
    req.setHeader('Authorization', `Bearer ${token}`);
    req.on('response', (resp) => {
      let raw = '';
      resp.on('data', (chunk) => { raw += chunk.toString(); });
      resp.on('end', () => {
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          try { resolve(JSON.parse(raw)); } catch (e) { reject(new Error(`bad json: ${raw}`)); }
        } else {
          reject(new Error(`HTTP ${resp.statusCode}: ${raw}`));
        }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// Strip "Electron/x.y.z" and app-name fragments from the default UA so Google
// OAuth doesn't reject the embedded webview. Chromium's "Chrome/..." token
// stays in place, which is what Google's disallowed_useragent check looks at.
function spoofUserAgent() {
  app.userAgentFallback = app.userAgentFallback
    .replace(/\sElectron\/\S+/i, '')
    .replace(/\sy-agent[^\s]*/i, '');
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'y-agent',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(APP_URL);

  // Open external links (target=_blank, window.open) in the user's default browser
  // instead of new Electron windows.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function createResultWindow() {
  resultWindow = new BrowserWindow({
    width: 360,
    height: 80,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    show: false,
    // Non-focusable so showing the popup does not steal focus from whichever
    // app the user moves to next (or from the prompt window itself).
    focusable: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });
  resultWindow.loadFile(path.join(__dirname, 'result-popup.html'));
  resultWindow.on('closed', () => { resultWindow = null; });
}

function showResultPopup(result) {
  if (!resultWindow) createResultWindow();
  const send = () => {
    resultWindow.webContents.send('result:show', { result });
    resultWindow.showInactive();
  };
  if (resultWindow.webContents.isLoading()) {
    resultWindow.webContents.once('did-finish-load', send);
  } else {
    send();
  }
}

ipcMain.handle('prompt:submit', async (_e, payload) => {
  const instruction = (payload && payload.instruction) || '';
  const mode = (payload && payload.mode) === 'copy' ? 'copy' : 'paste';
  try {
    const { result } = await callInlineApi(lastSelection, instruction);
    const text = typeof result === 'string' ? result : String(result ?? '');

    if (mode === 'copy') {
      clipboard.writeText(text);
      if (promptWindow) promptWindow.hide();
      showResultPopup(text);
    } else {
      // Paste-back: hide our window, bring the original app forward, then
      // write the clipboard and synthesize ⌘V. The short sleep gives macOS a
      // beat to actually switch focus before the keystroke is delivered.
      if (promptWindow) promptWindow.hide();
      await activateApp(lastFrontmostApp);
      await sleep(80);
      clipboard.writeText(text);
      await pasteViaCmdV();
    }
    return { ok: true };
  } catch (err) {
    console.error('[inline] request failed:', err.message);
    return { ok: false, error: err.message };
  }
});

ipcMain.on('prompt:close', () => {
  if (promptWindow) promptWindow.hide();
});

ipcMain.on('result:close', () => {
  if (resultWindow) resultWindow.hide();
});

app.whenReady().then(() => {
  spoofUserAgent();
  createWindow();
  createPromptWindow();
  createResultWindow();

  const registered = globalShortcut.register(SELECTION_SHORTCUT, handleSelectionShortcut);
  if (!registered) {
    console.error(`[selection] failed to register global shortcut ${SELECTION_SHORTCUT}`);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
