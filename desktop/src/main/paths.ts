import path from 'path';

// At runtime __dirname is dist/main, so project root is two levels up. icon.png
// lives at the project root; preload.js and the renderer bundle live under dist/.
export const PROJECT_ROOT = path.join(__dirname, '..', '..');
export const DIST_DIR = path.join(__dirname, '..');

export const ICON_PATH = path.join(PROJECT_ROOT, 'icon.png');
export const PRELOAD_PATH = path.join(DIST_DIR, 'preload.js');
export const RENDERER_INDEX = path.join(DIST_DIR, 'renderer', 'index.html');
