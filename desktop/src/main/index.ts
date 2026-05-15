import { app, BrowserWindow, globalShortcut } from 'electron';
import { SELECTION_SHORTCUTS } from './constants';
import { ICON_PATH } from './paths';
import { captureSelection } from './selection';
import { createMainWindow, createPromptWindow, showPromptWindow } from './windows';
import { registerIpcHandlers } from './ipc';

// Strip "Electron/x.y.z" and app-name fragments from the default UA so Google
// OAuth doesn't reject the embedded webview. Chromium's "Chrome/..." token
// stays in place, which is what Google's disallowed_useragent check looks at.
function spoofUserAgent(): void {
  app.userAgentFallback = app.userAgentFallback
    .replace(/\sElectron\/\S+/i, '')
    .replace(/\sy-agent[^\s]*/i, '');
}

async function handleSelectionShortcut(): Promise<void> {
  try {
    const selection = await captureSelection();
    showPromptWindow(selection);
  } catch (err) {
    console.error('[selection] capture failed:', err);
  }
}

registerIpcHandlers();

app.whenReady().then(() => {
  spoofUserAgent();
  // BrowserWindow.icon is ignored on macOS — the dock icon comes from the
  // bundle (.icns) when packaged, but in `npm start` dev mode we set it
  // explicitly so the Dock shows the Y logo instead of the generic Electron
  // gear.
  if (process.platform === 'darwin' && app.dock) {
    try {
      app.dock.setIcon(ICON_PATH);
    } catch {}
  }
  createMainWindow();
  createPromptWindow();

  let registeredAccel: string | null = null;
  for (const accel of SELECTION_SHORTCUTS) {
    if (globalShortcut.register(accel, handleSelectionShortcut)) {
      registeredAccel = accel;
      break;
    }
  }
  if (registeredAccel) {
    console.log(`[selection] global shortcut registered: ${registeredAccel}`);
  } else {
    console.error(
      `[selection] failed to register any of: ${SELECTION_SHORTCUTS.join(', ')}`,
    );
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
