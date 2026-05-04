const { app, BrowserWindow, clipboard, globalShortcut, ipcMain, shell, net } = require('electron');
const path = require('path');
const { exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

const APP_URL = 'https://yovy.app';
const SELECTION_SHORTCUT = 'Alt+Space';
const CLIPBOARD_POLL_TIMEOUT_MS = 300;
const CLIPBOARD_POLL_INTERVAL_MS = 20;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let mainWindow = null;
let promptWindow = null;
let lastSelection = '';

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

async function handleSelectionShortcut() {
  try {
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

ipcMain.handle('prompt:submit', async (_e, instruction) => {
  try {
    const { result } = await callInlineApi(lastSelection, instruction);
    // TODO(1981-paste-back): write `result` to clipboard and AppleScript ⌘V.
    console.log('[inline] result:', JSON.stringify(result));
    return { ok: true };
  } catch (err) {
    console.error('[inline] request failed:', err.message);
    return { ok: false, error: err.message };
  }
});

ipcMain.on('prompt:close', () => {
  if (promptWindow) promptWindow.hide();
});

app.whenReady().then(() => {
  spoofUserAgent();
  createWindow();
  createPromptWindow();

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
