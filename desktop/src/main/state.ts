import type { BrowserWindow } from 'electron';

// Module-level singletons shared across main-process modules. Kept on one
// object so any module can mutate the same fields without circular imports.
export const state: {
  mainWindow: BrowserWindow | null;
  promptWindow: BrowserWindow | null;
  lastSelection: string;
} = {
  mainWindow: null,
  promptWindow: null,
  lastSelection: '',
};
