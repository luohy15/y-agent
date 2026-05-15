export const APP_URL = 'https://yovy.app';

export const SELECTION_SHORTCUTS = ['Command+Control+Y'];

export const CLIPBOARD_POLL_TIMEOUT_MS = 1000;
export const CLIPBOARD_POLL_INTERVAL_MS = 20;

// Wait before issuing the AppleScript Cmd+C so the user has time to release the
// chord modifiers. Otherwise physical modifiers OR with our synthesized Cmd flag
// and the source app receives e.g. Cmd+Ctrl+C instead of Cmd+C.
export const PRE_KEYSTROKE_DELAY_MS = 120;
// Extra wait before the retry pass when the first capture returns empty —
// covers the long-tail case where the user holds the chord unusually long.
export const RETRY_DELAY_MS = 200;
