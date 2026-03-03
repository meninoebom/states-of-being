/**
 * Readings layer — weighted quality combinations with gating.
 * Structure matches Ralf's ReadingConfig for future compatibility.
 *
 * Each reading = { id, mix: {quality: weight}, gate: {quality: {above/below}} }
 * Output    = { id, value: 0-1, active: boolean }
 *
 * Ralf compatibility notes:
 *   - mix formula: value = Σ(quality × weight) / Σ(weights)
 *   - gate: all conditions must be met for reading to be active
 *   - hysteresis band (0.05) prevents oscillation near thresholds
 */

// --- Default reading configs ---
// These are the taste decisions that define what body states Song Blender responds to.
// Names are musical (flowing, agitated) not psychological (anger, fear).

export const DEFAULT_READINGS = [
  {
    id: 'flowing',
    mix: { coherence: 0.4, velocity: 0.3, symmetry: 0.3 },
    gate: { velocity: { above: 0.15 }, jerkiness: { below: 0.5 } },
  },
  {
    id: 'agitated',
    mix: { jerkiness: 0.45, velocity: 0.25 },
    gate: { jerkiness: { above: 0.3 } },
    // coherence inverted inline in mix would require preprocessing,
    // so we handle it in the mix step with a special "1-quality" convention
    _invertInMix: { coherence: 0.3 },
  },
  {
    id: 'stillness',
    mix: { contraction: 0.4, verticality: 0.3 },
    gate: { velocity: { below: 0.12 } },
    // stillness value is partly "how still" — invert velocity in mix
    _invertInMix: { velocity: 0.3 },
  },
  {
    id: 'reaching',
    mix: { wristSpread: 0.4, velocity: 0.2 },
    gate: { velocity: { above: 0.1 } },
    _invertInMix: { contraction: 0.4 },
  },
];

// Relational readings — only fire when two bodies are present.
// Fed with { synchrony, contrast, aggregate_energy } from computeRelational().
export const RELATIONAL_READINGS = [
  {
    id: 'unison',
    mix: { synchrony: 0.6, aggregate_energy: 0.4 },
    gate: { synchrony: { above: 0.55 } },
  },
  {
    id: 'opposition',
    mix: { contrast: 0.6, aggregate_energy: 0.4 },
    gate: { contrast: { above: 0.4 } },
  },
];

const HYSTERESIS_BAND = 0.05;
const LERP_RATE = 0.08;

export class ReadingsEngine {
  /**
   * @param {Array} configs — array of ReadingConfig objects (default: DEFAULT_READINGS)
   */
  constructor(configs = DEFAULT_READINGS) {
    this.configs = configs;

    // Per-reading state
    this.values = {};       // id → current smoothed value (0-1)
    this.gateState = {};    // "readingId:quality" → boolean (for hysteresis)

    for (const c of configs) {
      this.values[c.id] = 0;
    }
  }

  /**
   * Compute readings from body qualities.
   * @param {Object} qualities — { velocity, jerkiness, coherence, ... } all 0-1
   * @returns {Array} — [{ id, value, active }, ...]
   */
  update(qualities) {
    const results = [];

    for (const config of this.configs) {
      // --- Weighted mix ---
      let value = 0;
      let totalWeight = 0;

      for (const [quality, weight] of Object.entries(config.mix)) {
        value += (qualities[quality] ?? 0) * weight;
        totalWeight += weight;
      }
      // Inverted qualities (1 - quality)
      if (config._invertInMix) {
        for (const [quality, weight] of Object.entries(config._invertInMix)) {
          value += (1 - (qualities[quality] ?? 0)) * weight;
          totalWeight += weight;
        }
      }
      if (totalWeight > 0) value /= totalWeight;

      // --- Gate evaluation with hysteresis ---
      let active = true;
      if (config.gate) {
        for (const [quality, condition] of Object.entries(config.gate)) {
          const val = qualities[quality] ?? 0;
          const gateKey = `${config.id}:${quality}`;
          const wasActive = this.gateState[gateKey] ?? false;

          let gateActive;
          if (wasActive) {
            // To deactivate, must cross threshold by hysteresis band
            gateActive = true;
            if (condition.above !== undefined && val < condition.above - HYSTERESIS_BAND)
              gateActive = false;
            if (condition.below !== undefined && val > condition.below + HYSTERESIS_BAND)
              gateActive = false;
          } else {
            // To activate, must cross threshold + band
            gateActive = true;
            if (condition.above !== undefined && val < condition.above + HYSTERESIS_BAND)
              gateActive = false;
            if (condition.below !== undefined && val > condition.below - HYSTERESIS_BAND)
              gateActive = false;
          }

          this.gateState[gateKey] = gateActive;
          if (!gateActive) active = false;
        }
      }

      // --- Lerp toward target (smooth transitions) ---
      const target = active ? value : 0;
      this.values[config.id] += (target - this.values[config.id]) * LERP_RATE;

      results.push({
        id: config.id,
        value: this.values[config.id],
        active,
      });
    }

    return results;
  }
}
