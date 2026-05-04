const { app, BrowserWindow, clipboard, globalShortcut, shell } = require('electron');
const { exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

const APP_URL = 'https://yovy.app';
const SELECTION_SHORTCUT = 'Alt+Space';
const CLIPBOARD_POLL_TIMEOUT_MS = 300;
const CLIPBOARD_POLL_INTERVAL_MS = 20;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

async function handleSelectionShortcut() {
  try {
    const selection = await captureSelection();
    // TODO(1981-prompt-window): hand off to the prompt input window via IPC.
    console.log('[selection] captured:', JSON.stringify(selection));
  } catch (err) {
    console.error('[selection] capture failed:', err);
  }
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
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'y-agent',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadURL(APP_URL);

  // Open external links (target=_blank, window.open) in the user's default browser
  // instead of new Electron windows.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

app.whenReady().then(() => {
  spoofUserAgent();
  createWindow();

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
