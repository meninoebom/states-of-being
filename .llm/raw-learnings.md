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

## X-Forwarded-For: take the RIGHTMOST trusted entry for anti-abuse (2026-07-08, #12)
Behind a proxy (Railway edge), the real client IP is in X-Forwarded-For, formatted `client, proxy1, proxy2`. For rate limiting / anti-abuse, take the entry `trusted_hops` positions from the RIGHT (default 1 = rightmost), NOT the leftmost. The leftmost is client-controllable and lets an attacker spoof a fresh IP per request to evade per-IP limits. Only entries our own trusted proxy appends are reliable. Clamp the index so a misconfigured hop count (0/negative) can't IndexError on the hot path. See backend/app/client_ip.py.

## Testing the FastAPI backend with TestClient (2026-07-08, #19)
Two gotchas for `backend/tests/` when a test imports the app:
1. `app.config.Settings` requires `REPLICATE_API_TOKEN`; CI doesn't set it. A `conftest.py` doing `os.environ.setdefault("REPLICATE_API_TOKEN", "test-token")` (runs at collection import time) unblocks app import without a real token, since tests never make a real Replicate call.
2. slowapi rate-limits per client IP and the suite reuses one IP, so after 5 posts to a `5/hour` endpoint later tests 429. Set `limiter.enabled = False` in the client fixture. The `Limiter` object exposes `.enabled`.
Also: `asyncio.wait_for` around `asyncio.to_thread(...)` frees the awaiting request on timeout but CANNOT kill the worker thread; it runs to completion on the shared default executor. Good enough to un-hang the client; watch for pool starvation if many leak.
