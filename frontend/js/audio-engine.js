/**
 * Audio engine for Song Blender — manages Tone.js Players for song loops.
 * Uses Tone.Transport to keep all loops synchronized.
 */

import { CATEGORIES } from './constants.js';

const DEFAULT_FILTER_FREQ = {
  bass: 1000, texture: 8000, foundation: 5000, groove: 5000,
  harmonic_bed: 5000, hook: 5000, accent: 5000,
};

export class AudioEngine {
  constructor() {
    this.loaded = false;
    this.metadata = null;
    this.players = {};       // category → [{player, track}, ...]
    this.activeIndex = {};   // category → index of currently playing loop
    this.gains = {};         // category → Tone.Gain
    this.filters = {};       // category → Tone.Filter
    this.masterGain = null;
    this.masterFilter = null;
    this.onLoadProgress = null; // callback(loaded, total)
  }

  async load(metadata, baseUrl) {
    this.dispose();
    this.metadata = metadata;

    // Set Transport BPM so Tone knows the tempo
    Tone.Transport.bpm.value = metadata.bpm || 120;

    // Master chain
    this.masterFilter = new Tone.Filter({ frequency: 10000, type: 'lowpass', rolloff: -12 }).toDestination();
    this.masterGain = new Tone.Gain(0.8).connect(this.masterFilter);

    // Per-category gain + filter
    for (const cat of CATEGORIES) {
      const freq = DEFAULT_FILTER_FREQ[cat] || 5000;
      this.filters[cat] = new Tone.Filter({ frequency: freq, type: 'lowpass', rolloff: -12 }).connect(this.masterGain);
      this.gains[cat] = new Tone.Gain(0).connect(this.filters[cat]);
      this.players[cat] = [];
    }

    // Load all tracks as Tone.Players
    const tracks = metadata.tracks.filter(t => t.selected);
    let loadedCount = 0;

    const loadPromises = tracks.map(track => {
      const cat = track.category;
      if (!this.gains[cat]) return Promise.resolve(null);

      const url = baseUrl + track.url;
      return new Promise(resolve => {
        try {
          const player = new Tone.Player({
            url,
            loop: track.mode === 'loop',
            volume: track.volume || -12,
            onload: () => {
              loadedCount++;
              if (this.onLoadProgress) this.onLoadProgress(loadedCount, tracks.length);
              resolve({ player, track, cat });
            },
            onerror: (err) => {
              console.warn(`Failed to load ${track.file}:`, err);
              loadedCount++;
              if (this.onLoadProgress) this.onLoadProgress(loadedCount, tracks.length);
              resolve({ error: true });
            },
          }).connect(this.gains[cat]);
        } catch (err) {
          console.warn(`Error creating player for ${track.file}:`, err);
          resolve({ error: true });
        }
      });
    });

    const results = await Promise.all(loadPromises);
    let loadedOk = 0;
    let failed = 0;
    for (const r of results) {
      if (!r) continue;                       // skipped: unknown category
      if (r.error) { failed++; continue; }
      this.players[r.cat].push({ player: r.player, track: r.track });
      loadedOk++;
    }

    // Reject dead loads. If nothing playable loaded — every selected loop
    // failed (dead/missing files, decode failure), or the song had no selected
    // loops at all — this song is unplayable. Fail loudly instead of pretending
    // success with a silent engine. See issue #16.
    if (loadedOk === 0) {
      this.dispose();
      throw new Error(`Could not load any audio for "${metadata.name || 'this song'}".`);
    }
    if (failed > 0) {
      console.warn(`AudioEngine: ${failed}/${tracks.length} loops failed to load.`);
    }

    // Default: first loop in each category is active
    for (const cat of CATEGORIES) {
      this.activeIndex[cat] = 0;
    }

    this.loaded = true;
    console.log('AudioEngine loaded:', Object.entries(this.players).map(([k, v]) => `${k}:${v.length}`).join(', '));
  }

  start() {
    if (!this.loaded) return;

    this._barDur = this._computeBarDur();

    // Only sync+start the active loop per category (one at a time = clean mix).
    for (const [cat, entries] of Object.entries(this.players)) {
      const activeIdx = this.activeIndex[cat] ?? 0;
      for (let i = 0; i < entries.length; i++) {
        const { player, track } = entries[i];
        if (!player.loaded || track.mode !== 'loop') continue;
        try {
          this._setLoopPoints(player, track);
          if (i === activeIdx) {
            player.sync().start(0);
          }
          // Non-active loops stay loaded but not synced
        } catch (e) { console.warn(`Could not start ${track.file}:`, e); }
      }
    }

    Tone.Transport.start();
  }

  _computeBarDur() {
    const bpm = this.metadata?.bpm || 120;
    const timeSig = this.metadata?.time_signature || 4;
    return (60 / bpm) * timeSig;
  }

  /**
   * Drive the loop end from the loop's source duration (issue #18).
   *
   * `duration_sec` is the exact length the backend wrote the loop file to. For
   * non-vocal loops that is a whole number of nominal bars (to the sample), so
   * the loop stays locked to the Transport bar grid. It also fixes gapless
   * playback for lossy library formats: MP3/codec frame padding makes the
   * DECODED buffer longer than the real audio, so setting loopEnd from the
   * (larger) buffer duration — even rounded to whole bars — can push the loop
   * point past the real content and open a gap. Using the source duration stops
   * the loop before any padding, at the point where the 5ms fade-out hits zero.
   *
   * Vocal phrase loops are intentionally NOT bar-aligned: they loop at their
   * full phrase length (their `duration_sec`) rather than being snapped to a
   * bar, which would truncate the phrase. In this generative, non-beat-locked
   * mix a repeating vocal phrase drifting against the grid reads as texture.
   */
  _setLoopPoints(player, track) {
    const dur = track?.duration_sec;
    if (dur && dur > 0) {
      player.loopEnd = dur;
    }
    // No metadata duration: fall back to Tone's default (loop the whole buffer).
  }

  getBarDuration() {
    return this._barDur || this._computeBarDur();
  }

  /** Fade all categories to silence over fadeDurSec seconds. */
  fadeOutAll(fadeDurSec) {
    for (const cat of CATEGORIES) {
      this.gains[cat]?.gain.rampTo(0, fadeDurSec);
    }
  }

  stop() {
    Tone.Transport.stop();
    // Unsync players so they can be re-synced on next start
    for (const entries of Object.values(this.players)) {
      for (const { player } of entries) {
        try { player.unsync(); } catch (e) { /* ignore */ }
      }
    }
  }

  /** Set volume for a category in dB. Used by manual grid controls. */
  setCategoryVolume(category, db) {
    if (!this.gains[category]) return;
    this.gains[category].gain.rampTo(Tone.dbToGain(db), 0.3);
  }

  /** Mute/unmute a specific track by filename. */
  setTrackMuted(filename, muted) {
    for (const entries of Object.values(this.players)) {
      for (const { player, track } of entries) {
        if (track.file === filename) {
          player.volume.rampTo(muted ? -Infinity : (track.volume || -12), 0.3);
          return;
        }
      }
    }
  }

  /**
   * Swap the active loop in a category slot, bar-quantized.
   * @param {string} category
   * @param {number} index — index into this.players[category]
   */
  setActiveLoop(category, index) {
    const entries = this.players[category];
    if (!entries || index < 0 || index >= entries.length) {
      console.warn(`setActiveLoop: invalid category="${category}" index=${index}`);
      return;
    }
    if (this.activeIndex[category] === index) return;

    const barDur = this._barDur || this._computeBarDur();
    const oldIdx = this.activeIndex[category];
    this.activeIndex[category] = index;

    // Schedule swap on next bar boundary
    Tone.Transport.scheduleOnce((time) => {
      // Fade out old
      if (oldIdx < entries.length) {
        const old = entries[oldIdx].player;
        old.volume.rampTo(-Infinity, barDur, time);
        // Unsync after fade completes
        Tone.Transport.scheduleOnce(() => {
          try { old.unsync(); } catch (e) { console.warn(`unsync failed for ${category}:`, e); }
        }, time + barDur + 0.1);
      }
      // Fade in new
      const { player, track } = entries[index];
      if (player.loaded && track.mode === 'loop') {
        this._setLoopPoints(player, track);
        player.sync().start(0);
        player.volume.value = -Infinity;
        player.volume.rampTo(track.volume || -12, barDur, time);
      }
    }, `@${Tone.Transport.timeSignature}n`); // next bar boundary
  }

  /** Get available loops for a category with their section labels. */
  getLoopsForCategory(category) {
    const entries = this.players[category] || [];
    return entries.map(({ track }, i) => ({
      index: i,
      section: track.section,
      file: track.file,
      active: i === this.activeIndex[category],
    }));
  }

  dispose() {
    Tone.Transport.stop();
    Tone.Transport.cancel();
    for (const entries of Object.values(this.players)) {
      for (const { player } of entries) {
        try { player.unsync(); } catch (e) { /* ignore */ }
        try { player.dispose(); } catch (e) { /* ignore */ }
      }
    }
    for (const g of Object.values(this.gains)) { try { g.dispose(); } catch (e) { /* ignore */ } }
    for (const f of Object.values(this.filters)) { try { f.dispose(); } catch (e) { /* ignore */ } }
    if (this.masterGain) { try { this.masterGain.dispose(); } catch (e) { /* ignore */ } }
    if (this.masterFilter) { try { this.masterFilter.dispose(); } catch (e) { /* ignore */ } }
    this.players = {}; this.gains = {}; this.filters = {}; this.activeIndex = {};
    this.loaded = false; this.metadata = null;
  }
}
