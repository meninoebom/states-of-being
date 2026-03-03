/**
 * Mapping layer — connects readings to audio engine actions.
 * This is the taste layer: what body states do to the music.
 *
 * Uses Ralf-compatible action naming (set/* for continuous, trigger/* for discrete).
 * When Song Blender becomes a Ralf translator, this mapping moves into a Scene JSON.
 */

// Volume targets per reading (dB). Categories not listed stay at their current level.
const VOLUME_MAP = {
  flowing: {
    harmonic_bed: -6,
    texture: -8,
    foundation: -6,
    groove: -10,
    bass: -8,
    hook: -14,
    accent: -30,
  },
  agitated: {
    groove: -4,
    bass: -4,
    foundation: -8,
    accent: -6,
    harmonic_bed: -18,
    texture: -16,
    hook: -20,
  },
  stillness: {
    texture: -8,
    harmonic_bed: -12,
    bass: -20,
    foundation: -40,
    groove: -40,
    hook: -40,
    accent: -40,
  },
  reaching: {
    hook: -6,
    harmonic_bed: -6,
    texture: -10,
    foundation: -10,
    groove: -12,
    bass: -10,
    accent: -14,
  },
  // Relational readings (two bodies)
  unison: {
    hook: -4,
    harmonic_bed: -4,
    texture: -6,
    foundation: -8,
    groove: -10,
    bass: -8,
    accent: -16,
  },
  opposition: {
    groove: -2,
    accent: -4,
    bass: -4,
    foundation: -6,
    harmonic_bed: -14,
    texture: -14,
    hook: -16,
  },
};

// Baseline when no reading is strongly active
const QUIET_VOLUMES = {
  foundation: -20, groove: -20, bass: -14,
  harmonic_bed: -12, hook: -40, texture: -8, accent: -40,
};

import { CATEGORIES } from './constants.js';

/**
 * Apply readings to audio engine.
 * Blends volume targets from active readings proportional to their value.
 *
 * @param {Array} readings — [{ id, value, active }, ...]
 * @param {AudioEngine} engine
 * @param {Array|null} allowedCategories — if set, only these categories get volume; others muted
 */
export function applyMapping(readings, engine, allowedCategories = null) {
  if (!engine.loaded) return;

  // Start with quiet baseline
  const targetVol = { ...QUIET_VOLUMES };

  // Accumulate weighted volume contributions from active readings
  let totalWeight = 0;
  const contributions = {};
  for (const cat of CATEGORIES) contributions[cat] = 0;

  for (const reading of readings) {
    if (!reading.active || reading.value < 0.05) continue;
    const map = VOLUME_MAP[reading.id];
    if (!map) continue;

    const w = reading.value;
    totalWeight += w;

    for (const cat of CATEGORIES) {
      if (map[cat] !== undefined) {
        contributions[cat] += map[cat] * w;
      } else {
        contributions[cat] += QUIET_VOLUMES[cat] * w;
      }
    }
  }

  // Blend: if any readings active, use weighted average; otherwise quiet baseline
  if (totalWeight > 0) {
    for (const cat of CATEGORIES) {
      targetVol[cat] = contributions[cat] / totalWeight;
    }
  }

  // Phase-gate: mute categories not in current phase
  if (allowedCategories) {
    for (const cat of CATEGORIES) {
      if (!allowedCategories.includes(cat)) {
        targetVol[cat] = -60;
      }
    }
  }

  // Apply to engine with smooth ramp
  for (const cat of CATEGORIES) {
    engine.setCategoryVolume(cat, targetVol[cat]);
  }
}
