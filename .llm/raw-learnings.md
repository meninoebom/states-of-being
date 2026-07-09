# Raw Learnings (session capture — promote via /docs-gardener)

## 2026-07-08 — #14 guided vs debug /app surface

- The `?debug=1` gate is one module-level `DEBUG` const in `frontend/js/app.js`; it drives the default `mode` (`arc` guided / `manual` debug) and, at init, adds a `body.guided` or `body.debug` class and toggles visibility of `#mode-select`, `#loop-grid`, `#mode-toggle`. Later issues should branch on `DEBUG` / those body classes rather than re-parsing the query string.
- Non-obvious restructure: webcam acquisition moved from `setMode` to the Start action (`attemptStart`). This ties the camera permission prompt to an explicit user gesture and lets denial surface a retry banner at a clear moment instead of the old silent revert-to-manual. Consequence: `setMode` is now synchronous and can never leave `mode` out of sync with the toggle's active button.
- Skeleton overlay and debug-panel visibility now follow the webcam lifecycle (shown in `ensureWebcam` success, hidden in `stopWebcam`), not the mode switch. Skeleton is user-facing "it sees me" feedback; debug panel is gated additionally by `DEBUG`.

## Aligning a skeleton/canvas overlay to an object-fit:cover video (#15, 2026-07-08)
MediaPipe landmarks are normalized to the raw camera frame. When you overlay a
canvas on a `<video>` styled `object-fit: cover`, the video is scaled+cropped to
its box, so mapping `x*W, y*H` drifts joints off the body whenever the box aspect
differs from the camera aspect. Fix: replicate cover math in JS.
`scale = max(W/vw, H/vh); dw=vw*scale; dh=vh*scale; offX=(W-dw)/2; offY=(H-dh)/2;`
then `px = offX + x*dw` (or `(1-x)*dw` to match a CSS `scaleX(-1)` mirror).
This makes alignment correct for ANY box/video aspect, so you can freely bound
the stage with max-width/max-height. Also DPR-scale the backing store
(`canvas.width = cssW * devicePixelRatio; ctx.setTransform(dpr,0,0,dpr,0,0)`) or a
full-size overlay looks soft next to the native-res video.

## 2026-07-08 — Mirror stage aspect-ratio is NOT what keeps joints aligned (#6)
The CSS comment on `#mirror-stage` says the camera-matched `aspect-ratio` exists
"so object-fit: cover never crops." That is outdated. `drawSkeletons` in app.js
already replicates the cover-crop transform (`scale = Math.max(W/vw, H/vh)`,
centered offsets, `mapX/mapY`) using the real `video.videoWidth/Height` against
the stage rect. So the stage can be ANY aspect ratio and joints stay aligned;
cropping is handled in the draw math. This is what let the mobile full-screen
dance view drop the aspect-ratio (via `aspect-ratio: auto !important`, overriding
the inline value app.js sets) and fill a portrait phone with a landscape feed.

Related gotcha: on mobile full-screen the header is hidden, and `#status` lives
inside it. Any user-facing prompt written only to `setStatus()` is invisible on
mobile there. Prompts that must reach a dancer across the room have to drive
`#phase-indicator` (the floating on-stage element), not just `#status`.
