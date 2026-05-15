import { dialog, shell } from 'electron';
import http from 'http';
import { state } from './state';
import { APP_URL } from './constants';

// gsi opens accounts.google.com (sometimes via about:blank first); any of
// these URLs means the user is trying to sign in.
export function isOAuthPopupUrl(url: string): boolean {
  if (!url || url === 'about:blank') return true;
  return (
    /^https:\/\/(accounts|content|oauth2)\.google\.com\//i.test(url) ||
    /^https:\/\/[^/]+\.googleusercontent\.com\//i.test(url)
  );
}

// Loopback OAuth: one in-flight at a time. Re-triggering while pending just
// re-opens the browser tab rather than spawning a second server.
let loopbackServer: http.Server | null = null;

function getServerPort(server: http.Server): number | null {
  const addr = server.address();
  if (!addr || typeof addr !== 'object') return null;
  return addr.port;
}

function startLoopbackOAuth(): Promise<{ token: string; email: string }> {
  return new Promise((resolve, reject) => {
    if (loopbackServer) {
      const port = getServerPort(loopbackServer);
      if (port != null) {
        const redirectUrl = `http://127.0.0.1:${port}/cb`;
        shell.openExternal(`${APP_URL}/?auth_redirect=${encodeURIComponent(redirectUrl)}`);
      }
      return;
    }
    const server = http.createServer((req, res) => {
      const u = new URL(req.url || '', 'http://127.0.0.1');
      if (u.pathname !== '/cb') {
        res.writeHead(404);
        res.end('Not found');
        return;
      }
      const token = u.searchParams.get('auth_token');
      const email = u.searchParams.get('auth_email');
      if (!token || !email) {
        res.writeHead(400);
        res.end('Missing auth_token / auth_email');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(
        '<!doctype html><meta charset="utf-8"><title>Signed in</title><body style="font-family:-apple-system,system-ui,sans-serif;padding:60px;text-align:center;color:#444"><h2 style="margin-bottom:8px">y-agent: signed in</h2><p>You can close this tab and return to the app.</p></body>',
      );
      try {
        server.close();
      } catch {}
      loopbackServer = null;
      resolve({ token, email });
    });
    server.on('error', (err) => {
      loopbackServer = null;
      reject(err);
    });
    server.listen(0, '127.0.0.1', () => {
      loopbackServer = server;
      const port = getServerPort(server);
      if (port == null) {
        reject(new Error('loopback server bound to a non-IP address'));
        return;
      }
      const redirectUrl = `http://127.0.0.1:${port}/cb`;
      shell.openExternal(`${APP_URL}/?auth_redirect=${encodeURIComponent(redirectUrl)}`);
    });
  });
}

export async function ensureLoggedInViaBrowser(): Promise<void> {
  // Re-entrant guard: if a flow is already pending, startLoopbackOAuth's
  // early-return will just re-open the browser tab.
  try {
    const { token, email } = await startLoopbackOAuth();
    const { mainWindow } = state;
    if (!mainWindow || mainWindow.isDestroyed()) return;
    await mainWindow.webContents.executeJavaScript(
      `localStorage.setItem('jwt_token', ${JSON.stringify(token)});` +
        `localStorage.setItem('user_email', ${JSON.stringify(email)});`,
    );
    mainWindow.webContents.reload();
  } catch (err) {
    const message = (err as Error).message;
    console.error('[auth] loopback flow failed:', message);
    const { mainWindow } = state;
    if (mainWindow && !mainWindow.isDestroyed()) {
      dialog.showMessageBox(mainWindow, {
        type: 'error',
        title: 'Sign-in failed',
        message: 'Could not complete sign-in',
        detail: message,
      });
    }
  }
}
