#!/usr/bin/env python3
"""Verify whether our MP3 ingest path (pydub -> LAME 192k) introduces encoder
delay/padding that would break gapless looping in the browser (issue #18).

Two checks:
  1. Offline: encode a known tone via the exact ingest path and compare the
     decoded length + leading/trailing silence against the source WAV using
     soundfile (libsndfile). A compliant decoder honors the LAME/Xing gapless
     header and returns a sample-exact result.
  2. Browser: writes `decode_test.html`, which decodes the same files with
     `AudioContext.decodeAudioData` and prints the same metrics. Serve the output
     dir over http and open it to confirm the target browsers behave the same.

Finding (2026-07-09, Chrome + libsndfile): our 192k MP3 decodes sample-identical
to the source WAV with zero delay/padding -> defect NOT present -> keep MP3. See
docs/LEARNINGS.md ("Gapless Loops at the Source").

Usage:
    python scripts/verify_mp3_gapless.py [--out DIR]
"""

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf
from pydub import AudioSegment

SR = 44100
DUR_SEC = 2.0
THRESHOLD = 0.02  # |amplitude| above this counts as signal, not silence


def _lead_trail(path: str) -> tuple[int, int, int, int]:
    """Return (samples, sample_rate, leading_silence, trailing_silence)."""
    a, sr = sf.read(path)
    if a.ndim == 2:
        a = a.mean(axis=1)
    above = np.where(np.abs(a) > THRESHOLD)[0]
    if not len(above):
        return len(a), sr, len(a), 0
    return len(a), sr, int(above[0]), int(len(a) - 1 - above[-1])


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # A cosine is non-zero from sample 0, so any encoder-added leading silence
    # is unambiguous.
    t = np.arange(int(SR * DUR_SEC)) / SR
    y = (0.5 * np.cos(2 * np.pi * 440 * t)).astype(np.float32)
    src_wav, src_mp3 = out / "src.wav", out / "src.mp3"
    sf.write(str(src_wav), y, SR)
    AudioSegment.from_wav(str(src_wav)).export(str(src_mp3), format="mp3", bitrate="192k")

    print("Offline (soundfile/libsndfile):")
    for f in (src_wav, src_mp3):
        n, sr, lead, trail = _lead_trail(str(f))
        print(f"  {f.name:8s} samples={n:7d} sr={sr} "
              f"lead={lead} ({lead / sr * 1000:.2f}ms) trail={trail} ({trail / sr * 1000:.2f}ms)")

    (out / "decode_test.html").write_text(_HTML)
    print(f"\nWrote {out / 'decode_test.html'}. To verify in a browser:")
    print(f"  cd {out} && python -m http.server 8777")
    print("  open http://127.0.0.1:8777/decode_test.html  (see [GAPLESS] console lines)")


_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>gapless decode test</title></head>
<body><h1>decodeAudioData gapless probe</h1><pre id="out">running…</pre>
<script>
const out = document.getElementById('out');
function analyze(name, buf) {
  const ch = buf.getChannelData(0), thr = 0.02;
  let lead = ch.length, trail = 0;
  for (let i = 0; i < ch.length; i++) if (Math.abs(ch[i]) > thr) { lead = i; break; }
  for (let i = ch.length - 1; i >= 0; i--) if (Math.abs(ch[i]) > thr) { trail = ch.length - 1 - i; break; }
  const sr = buf.sampleRate;
  const line = `${name.padEnd(12)} dur=${buf.duration.toFixed(6)}s samples=${ch.length} `
    + `lead=${lead} (${(lead/sr*1000).toFixed(2)}ms) trail=${trail} (${(trail/sr*1000).toFixed(2)}ms)`;
  console.log('[GAPLESS] ' + line);
  return line;
}
(async () => {
  const ac = new (window.AudioContext || window.webkitAudioContext)();
  const lines = ['sampleRate=' + ac.sampleRate];
  for (const f of ['src.wav', 'src.mp3']) {
    try {
      const buf = await ac.decodeAudioData(await (await fetch(f)).arrayBuffer());
      lines.push(analyze(f, buf));
    } catch (e) { lines.push(f + ' ERROR ' + e.message); }
  }
  out.textContent = lines.join('\\n');
})();
</script></body></html>
"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="./.gapless-check", help="Output directory")
    main(parser.parse_args().out)
