/**
 * Audio engine for Song Blender — manages Tone.js Players for song loops.
 * Uses Tone.Transport to keep all loops synchronized.
 */

const CATEGORIES = ['foundation', 'groove', 'bass', 'harmonic_bed', 'hook', 'texture', 'accent'];

const DEFAULT_FILTER_FREQ = {
  bass: 1000, texture: 8000, foundation: 5000, groove: 5000,
  harmonic_bed: 5000, hook: 5000, accent: 5000,
};

export class AudioEngine {
  constructor() {
    this.loaded = false;
    this.metadata = null;
    this.players = {};       // category → [{player, track}, ...]
    this.gains = {};         // category → Tone.Gain
    this.filters = {};       // category → Tone.Filter
    this.masterGain = null;
    this.masterFilter = null;
    this.oneshotCooldown = 0;
    this.categoryVolumes = {};
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
              resolve(null);
            },
          }).connect(this.gains[cat]);
        } catch (err) {
          console.warn(`Error creating player for ${track.file}:`, err);
          resolve(null);
        }
      });
    });

    const results = await Promise.all(loadPromises);
    for (const r of results) {
      if (r) this.players[r.cat].push({ player: r.player, track: r.track });
    }

    this.loaded = true;
    console.log('AudioEngine loaded:', Object.entries(this.players).map(([k, v]) => `${k}:${v.length}`).join(', '));
  }

  start() {
    if (!this.loaded) return;

    const bpm = this.metadata?.bpm || 120;
    const timeSig = this.metadata?.time_signature || 4;
    const barDur = (60 / bpm) * timeSig; // seconds per bar

    // Sync all loop players to Transport so they share the same clock.
    // Quantize each loop's end point to exact bar boundaries to prevent drift.
    for (const [cat, entries] of Object.entries(this.players)) {
      for (const { player, track } of entries) {
        if (!player.loaded || track.mode !== 'loop') continue;
        try {
          // Snap loop length to nearest whole bar count
          const rawDur = player.buffer.duration;
          const barCount = Math.round(rawDur / barDur);
          if (barCount > 0) {
            player.loopEnd = barCount * barDur;
          }
          player.sync().start(0);
        } catch (e) { console.warn(`Could not start ${track.file}:`, e); }
      }
    }

    Tone.Transport.start();
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
    this.categoryVolumes[category] = db;
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

  /** Update audio based on emotion readings. Called from movement layer. */
  updateFromReadings(readings) {
    if (!this.loaded) return;

    // Default: everything quiet
    const vol = {
      foundation: -20, groove: -20, bass: -14,
      harmonic_bed: -12, hook: -60, texture: -8, accent: -60,
    };

    const { flowing = 0, agitated = 0, stillness = 0, reaching = 0 } = readings;

    if (flowing > 0.3) {
      vol.foundation = -6; vol.groove = -8; vol.bass = -6;
      vol.harmonic_bed = -8; vol.texture = -10;
    }
    if (stillness > 0.3) {
      vol.foundation = -60; vol.groove = -60; vol.bass = -16;
      vol.harmonic_bed = -10; vol.texture = -6;
    }
    if (agitated > 0.3) {
      vol.foundation = -8; vol.groove = -4; vol.bass = -4;
      vol.harmonic_bed = -20; vol.texture = -18;
    }

    for (const [cat, gain] of Object.entries(this.gains)) {
      const targetDb = vol[cat] !== undefined ? vol[cat] : -20;
      gain.gain.rampTo(Tone.dbToGain(targetDb), 1.5);
      this.categoryVolumes[cat] = targetDb;
    }

    // Oneshot triggering on agitation spikes
    const timeSinceLast = performance.now() - this.oneshotCooldown;
    if (timeSinceLast > 500 && agitated > 0.4 && Math.random() < agitated * 0.02) {
      this._triggerRandomOneshot('accent', -2);
      this.oneshotCooldown = performance.now();
    }
  }

  _triggerRandomOneshot(category, volumeDb) {
    const entries = this.players[category];
    if (!entries || entries.length === 0) return;
    const { player } = entries[Math.floor(Math.random() * entries.length)];
    if (!player.loaded) return;
    try {
      if (this.gains[category]) {
        this.gains[category].gain.rampTo(Tone.dbToGain(volumeDb), 0.05);
        this.gains[category].gain.rampTo(Tone.dbToGain(-60), 2, Tone.now() + 0.5);
      }
      player.seek(0);
      player.start();
    } catch (e) { console.warn(`Oneshot trigger failed (${category}):`, e); }
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
    this.players = {}; this.gains = {}; this.filters = {};
    this.loaded = false; this.metadata = null; this.categoryVolumes = {};
  }
}
