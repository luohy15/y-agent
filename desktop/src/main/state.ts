import type { BrowserWindow } from 'electron';

// Module-level singletons shared across main-process modules. Kept on one
// object so any module can mutate the same fields without circular imports.
export const state: {
  mainWindow: BrowserWindow | null;
  promptWindow: BrowserWindow | null;
  lastSelection: string;
  // True when the Yovy main window was the front Yovy window at the moment
  // the popup was triggered. Used on dismiss to decide whether to `app.hide()`
  // Yovy (returning focus to the previous app) or leave the main window up.
  yovyWasFront: boolean;
} = {
  mainWindow: null,
  promptWindow: null,
  lastSelection: '',
  yovyWasFront: false,
};
