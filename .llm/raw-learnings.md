# Raw Learnings (session capture — promote via /docs-gardener)

## 2026-07-09 — #18 gapless loops at the source

### Audio-timing: quantize loop LENGTH to the nominal grid, not the downbeat span
**Problem:** Instrument loops had audible seams. Cuts were snapped to downbeats then
"fine-tuned" to nearby silence, which shifted them off the beat grid (loops like
4.043 bars). The frontend hid this by rounding `loopEnd` to whole bars.
**Solution:** Cut on downbeats only, then trim/zero-pad each loop to an exact multiple
of the *nominal* bar (`60/bpm * time_signature`). Measure exactness against the nominal
grid, because the Transport plays at the nominal tempo and real downbeats drift from it.
A real datum: `highest/bass_intro_1` had `bars: 9` but `duration_sec: 20.03` while
9 nominal bars = 22.27s — the old library was badly grid-misaligned.
**Gotcha:** store `duration_sec` at sample-fine precision (6 dp, not 3). Rounding to 3
dp is ~22 samples of error at 44.1k, and because different loops round differently the
layers drift apart audibly over a multi-minute session.
**Code ref:** `backend/app/services/loop_chopper.py` (non-vocal branch of `chop_stem`).

### MP3 gapless: verify browser decode empirically, don't assume
**Finding:** our pydub/LAME 192k export writes the Xing/LAME gapless header, and Chrome's
`decodeAudioData` honors it — a known 2s tone round-trips sample-identical (0 leading
silence, 0 padding). libsndfile agrees. So the "MP3 encoder delay breaks gapless" worry
was refuted for our pipeline; kept MP3. The ~45ms lead/trail seen in a *real* library MP3
was content silence from the OLD snap-to-silence chopper, not codec delay.
**Method (reusable):** `scripts/verify_mp3_gapless.py` + browser `decodeAudioData` probe.
Use a signal that is non-zero from sample 0 so any encoder-added lead is unambiguous.

### End of Issue Retrospective
**What went well:** TDD on the chopper math caught the trim-vs-pad direction early; the
controlled-tone browser test cleanly separated "codec delay" from "content silence".
**What took longer:** deciding duration_sec precision (drift analysis) and reasoning
about loopEnd vs buffer.duration for WAV (live) vs padded MP3 (library) paths.
**Would do differently / remaining:** the 4 curated songs still need a one-time re-ingest
against the deployed new backend (needs source audio) + by-ear check; can't be done from
an agent lacking the source files. Consider committing source stems or a re-ingest fixture.

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

## 2026-07-08 — `_is_front_loaded` uses mean energy, not energy share (bug, #17)
`loop_chopper._is_front_loaded` compares per-sample MEAN energy of the first
fifth against the whole loop (`np.mean(front**2) / np.mean(total**2)`). CLAUDE.md
documents the intent as an energy SHARE ("first 20% has >75% of total energy").
For an evenly-loud loop the mean ratio is 1.0 (>0.75) so it is wrongly flagged
front-loaded and discarded, making the vocal filter far more aggressive than
intended. Left as `xfail(strict=True)` in test_loop_chopper.py pending Brandon's
by-ear decision. Fix would be a share comparison: `sum(front**2)/sum(total**2)`.

Test gotcha: snap-to-silence pulls a section boundary BACKWARD into an adjacent
loud region (0.15s window), so a chop_stem energy-drop test needs a >0.15s guard
gap between the loud region and the silent section's start, or the segment grabs
loud audio and survives the energy filter.
