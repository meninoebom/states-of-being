# Raw Learnings (session capture — promote via /docs-gardener)

## 2026-07-08 — #16 silent-failure honesty across the song-load path

- The audio load path faked success because each `Tone.Player` was wrapped in a Promise whose `onerror` **resolved** (with `null`) rather than rejecting. `Promise.all` then never fails, so a song with every audio file dead still resolved and set `loaded = true`. Pattern to watch: a per-item Promise that swallows its own error to keep `Promise.all` alive silently discards failures. Fix is to count real successes and throw when zero are playable.
- Honest failure needs all three layers to cooperate: `audio-engine.load` throws → `app.js` re-throws (not `return`) → `song-picker._select` awaits the handler and deselects the card. If any layer swallows, the card stays selected and Start is enabled over a silent engine.
- The picker's `onSongSelected` is awaited now, so a downstream load failure propagates back to card state. Added a sibling `picker.onError(msg)` callback (wired to `setStatus` in app.js) for the picker's own fetch failures. Any new picker fetch should check `res.ok`.

## 2026-07-08 — #14 guided vs debug /app surface

- The `?debug=1` gate is one module-level `DEBUG` const in `frontend/js/app.js`; it drives the default `mode` (`arc` guided / `manual` debug) and, at init, adds a `body.guided` or `body.debug` class and toggles visibility of `#mode-select`, `#loop-grid`, `#mode-toggle`. Later issues should branch on `DEBUG` / those body classes rather than re-parsing the query string.
- Non-obvious restructure: webcam acquisition moved from `setMode` to the Start action (`attemptStart`). This ties the camera permission prompt to an explicit user gesture and lets denial surface a retry banner at a clear moment instead of the old silent revert-to-manual. Consequence: `setMode` is now synchronous and can never leave `mode` out of sync with the toggle's active button.
- Skeleton overlay and debug-panel visibility now follow the webcam lifecycle (shown in `ensureWebcam` success, hidden in `stopWebcam`), not the mode switch. Skeleton is user-facing "it sees me" feedback; debug panel is gated additionally by `DEBUG`.
