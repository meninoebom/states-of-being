/**
 * Minimal production error reporting + usage counters.
 *
 * Captures unhandled frontend errors (window.onerror / unhandledrejection) and
 * POSTs a small structured payload to the backend, which logs one stdout line
 * Railway captures. No paid SaaS, no bundle: just fetch. Also exposes
 * reportEvent() so the app can bump usage counters (session_started,
 * song_played) we can tune mappings against.
 *
 * Loaded as a module BEFORE app.js in index.html so handlers are installed
 * before any app code runs and errors during init are still captured.
 */

const API_URL = window.location.hostname === 'localhost'
  ? 'http://localhost:8000'
  : 'https://song-blender-api-production.up.railway.app';

// A single bad frame can throw every animation tick; cap reports so a broken
// user does not spam the backend (and our costs). Reset only on reload.
const MAX_REPORTS = 25;
let sent = 0;

// Dedupe identical messages within a session so one recurring error is logged
// once, not thousands of times.
const seen = new Set();

function post(path, body) {
  try {
    fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true, // still delivered if the page is unloading
    }).catch(() => {}); // reporting must never throw or block the app
  } catch {
    // Ignore: telemetry is best-effort and must not affect the user.
  }
}

function reportError({ message, source, lineno, colno, stack }) {
  if (sent >= MAX_REPORTS) return;
  const key = `${message}@${source}:${lineno}`;
  if (seen.has(key)) return;
  seen.add(key);
  sent += 1;

  post('/api/client-error', {
    message: String(message || 'unknown error').slice(0, 1000),
    source: source ? String(source).slice(0, 1000) : null,
    lineno: Number.isFinite(lineno) ? lineno : null,
    colno: Number.isFinite(colno) ? colno : null,
    stack: stack ? String(stack).slice(0, 4000) : null,
    page: window.location.href.slice(0, 1000),
    user_agent: navigator.userAgent.slice(0, 500),
  });
}

/** Bump an allowlisted usage counter (session_started, song_played). */
export function reportEvent(event) {
  post('/api/client-event', { event });
}

window.addEventListener('error', (e) => {
  reportError({
    message: e.message,
    source: e.filename,
    lineno: e.lineno,
    colno: e.colno,
    stack: e.error && e.error.stack,
  });
});

window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason;
  reportError({
    message: reason && reason.message ? reason.message : `unhandled rejection: ${reason}`,
    source: 'unhandledrejection',
    stack: reason && reason.stack,
  });
});

// One session begins when the app script loads.
reportEvent('session_started');
