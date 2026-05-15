import { BrowserWindow, shell } from 'electron';
import { state } from './state';
import { APP_URL } from './constants';
import { ICON_PATH, PRELOAD_PATH, RENDERER_INDEX } from './paths';
import { ensureLoggedInViaBrowser, isOAuthPopupUrl } from './oauth';

export function createPromptWindow(): BrowserWindow {
  const promptWindow = new BrowserWindow({
    width: 480,
    height: 96,
    // type:'panel' = NSPanel on macOS. Critical for the Spotlight-style UX:
    // showing the popup does NOT activate Yovy as the front app, so
    // dismissing it doesn't surface the main window or steal focus from
    // whatever app the user came from. Panels still accept keyboard input.
    type: 'panel',
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: PRELOAD_PATH,
    },
  });
  promptWindow.loadFile(RENDERER_INDEX);
  // Float above full-screen apps too — otherwise ⌘⌃Y is useless while the
  // user has VSCode / a browser in macOS full-screen mode.
  promptWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  // Don't auto-hide on blur — once the result is showing the user often
  // clicks into another app to paste the (already-copied) text, and we
  // shouldn't disappear behind their back. Esc is the canonical dismiss.
  promptWindow.on('closed', () => {
    state.promptWindow = null;
  });
  state.promptWindow = promptWindow;
  return promptWindow;
}

export function showPromptWindow(selection: string): void {
  if (!state.promptWindow) createPromptWindow();
  state.lastSelection = selection;
  const promptWindow = state.promptWindow!;
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

export function createMainWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'y-agent',
    icon: ICON_PATH,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(APP_URL);

  // Google's "disallowed_useragent" policy blocks OAuth inside any embedded
  // browser (including Electron), so we can't run Google Sign-In in-app no
  // matter how we spoof the UA. Instead we use the canonical native-app
  // pattern: open yovy.app in the user's real browser with ?auth_redirect=
  // pointing at a loopback HTTP server we run here. The web app finishes the
  // GIS flow there, then redirects to our loopback URL with the JWT as a
  // query param. We catch it, inject into mainWindow's localStorage, and
  // reload. See ensureLoggedInViaBrowser() for the flow.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isOAuthPopupUrl(url)) {
      ensureLoggedInViaBrowser();
      return { action: 'deny' };
    }
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // On initial load (and reloads), if the user is not signed in yet, kick off
  // the loopback flow automatically so they don't have to hunt for the GIS
  // button (which won't work in-app anyway).
  mainWindow.webContents.on('did-finish-load', async () => {
    if (!state.mainWindow || state.mainWindow.isDestroyed()) return;
    const url = mainWindow.webContents.getURL();
    if (!url.startsWith(APP_URL)) return;
    try {
      const token = await mainWindow.webContents.executeJavaScript(
        'localStorage.getItem("jwt_token")',
      );
      if (!token) ensureLoggedInViaBrowser();
    } catch (err) {
      console.error('[auth] login-state probe failed:', (err as Error).message);
    }
  });

  mainWindow.on('closed', () => {
    state.mainWindow = null;
  });
  state.mainWindow = mainWindow;
  return mainWindow;
}
