export const APP_URL = 'https://yovy.app';

// Primary first; fall back to the next if registration fails (another app or
// the system already grabbed the accelerator). Alt+Space is reserved by macOS
// (window menu) so we avoid it.
export const SELECTION_SHORTCUTS = [
  'CommandOrControl+Shift+Y',
  'CommandOrControl+Alt+Y',
  'CommandOrControl+Shift+J',
];

export const CLIPBOARD_POLL_TIMEOUT_MS = 300;
export const CLIPBOARD_POLL_INTERVAL_MS = 20;
