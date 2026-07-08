/**
 * Movement detection — extracts body qualities from MediaPipe Pose landmarks.
 * Ported from Calm Mirror (index.html lines 560-835).
 *
 * Usage:
 *   const detector = new MovementDetector();
 *   // In detection loop:
 *   const qualities = detector.update(landmarks, timestamp);
 *   // qualities = { velocity, jerkiness, symmetry, coherence, contraction,
 *   //               verticality, ankleSpread, wristSpread } (all 0-1)
 */

// --- One-Euro Filter (smooth noisy landmark coordinates) ---

class LowPassFilter {
  constructor() { this.y = null; this.s = null; }
  filter(value, alpha) {
    if (this.y === null) { this.s = value; }
    else { this.s = alpha * value + (1 - alpha) * this.s; }
    this.y = value;
    return this.s;
  }
}

class OneEuroFilter {
  constructor(minCutoff = 1.0, beta = 0.007, dCutoff = 1.0) {
    this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff;
    this.xFilter = new LowPassFilter(); this.dxFilter = new LowPassFilter();
    this.lastTime = null;
  }
  alpha(cutoff, dt) {
    return 1.0 / (1.0 + 1.0 / (2 * Math.PI * cutoff) / dt);
  }
  filter(value, timestamp) {
    if (this.lastTime === null) {
      this.lastTime = timestamp;
      return this.xFilter.filter(value, 1.0);
    }
    const dt = Math.max(timestamp - this.lastTime, 1e-6);
    this.lastTime = timestamp;
    const dValue = (value - (this.xFilter.s ?? value)) / dt;
    const edValue = this.dxFilter.filter(dValue, this.alpha(this.dCutoff, dt));
    const cutoff = this.minCutoff + this.beta * Math.abs(edValue);
    return this.xFilter.filter(value, this.alpha(cutoff, dt));
  }
}

// --- Adaptive Range Normalizer ---
// Tracks observed min/max, normalizes to 0-1. Expands instantly, contracts slowly.

class AdaptiveRange {
  constructor(initialMin = 0, initialMax = 0.001, decayRate = 0.998) {
    this.min = initialMin;
    this.max = initialMax;
    this.decayRate = decayRate;
  }
  normalize(value) {
    if (value < this.min) this.min = value;
    if (value > this.max) this.max = value;
    const mid = (this.min + this.max) / 2;
    this.min += (mid - this.min) * (1 - this.decayRate);
    this.max -= (this.max - mid) * (1 - this.decayRate);
    const range = this.max - this.min;
    if (range < 0.0001) return 0.5;
    return Math.max(0, Math.min(1, (value - this.min) / range));
  }
}

// --- Helpers ---

function dist(a, b) {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

function mean(arr) {
  return arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
}

function jointVelocities(landmarks, prev, joints) {
  const vels = [];
  for (const idx of joints) {
    if (landmarks[idx].visibility > 0.3 && prev[idx].visibility > 0.3) {
      vels.push(dist(landmarks[idx], prev[idx]));
    }
  }
  return vels;
}

// --- Joint indices (MediaPipe Pose) ---
const LEFT_JOINTS = [11, 13, 15, 23, 25, 27];
const RIGHT_JOINTS = [12, 14, 16, 24, 26, 28];
const BODY_JOINTS = [...LEFT_JOINTS, ...RIGHT_JOINTS];
const WINDOW = 30; // ~1 second at 30fps

export class MovementDetector {
  constructor() {
    // Landmark smoothing (33 landmarks, x + y each)
    this.landmarkFilters = Array.from({ length: 33 }, () => ({
      x: new OneEuroFilter(1.0, 0.007, 1.0),
      y: new OneEuroFilter(1.0, 0.007, 1.0),
    }));

    // Adaptive normalizers per quality
    this.ranges = {
      velocity:      new AdaptiveRange(0, 0.005),
      jerk:          new AdaptiveRange(0, 0.001),
      contraction:   new AdaptiveRange(0.01, 0.15),
      verticality:   new AdaptiveRange(0.02, 0.2),
      symmetry:      new AdaptiveRange(0, 1, 0.999),
      coherence:     new AdaptiveRange(0, 0.01, 0.999),
      ankleSpread:   new AdaptiveRange(0, 0.2),
      wristSpread:   new AdaptiveRange(0, 0.3),
    };

    // History buffers
    this.prevLandmarks = null;
    this.prevPrevLandmarks = null;
    this.velocityHistory = [];
    this.accelHistory = [];
    this.jerkHistory = [];
    this.leftVelHistory = [];
    this.rightVelHistory = [];
    this.velDiffHistory = [];
  }

  /** Smooth raw MediaPipe landmarks through One-Euro filters. */
  smooth(landmarks, timestamp) {
    return landmarks.map((lm, i) => ({
      x: this.landmarkFilters[i].x.filter(lm.x, timestamp),
      y: this.landmarkFilters[i].y.filter(lm.y, timestamp),
      visibility: lm.visibility,
    }));
  }

  /**
   * Main entry point. Takes raw landmarks + timestamp, returns qualities object.
   * Call once per frame (~30fps).
   */
  update(rawLandmarks, timestamp) {
    const landmarks = this.smooth(rawLandmarks, timestamp);
    return this._computePrimitives(landmarks);
  }

  _computePrimitives(landmarks) {
    const out = {
      velocity: 0, jerkiness: 0, contraction: 0.5, verticality: 0.5,
      symmetry: 0.5, coherence: 0.5, ankleSpread: 0.5, wristSpread: 0.5,
    };

    // === SHAPE PRIMITIVES ===

    // Contraction: wrist-to-hip distance + shoulder width (inverted)
    const lWristHip = (landmarks[15].visibility > 0.3 && landmarks[23].visibility > 0.3)
      ? dist(landmarks[15], landmarks[23]) : null;
    const rWristHip = (landmarks[16].visibility > 0.3 && landmarks[24].visibility > 0.3)
      ? dist(landmarks[16], landmarks[24]) : null;
    const shoulderWidth = (landmarks[11].visibility > 0.3 && landmarks[12].visibility > 0.3)
      ? dist(landmarks[11], landmarks[12]) : null;

    if (lWristHip !== null || rWristHip !== null) {
      const avgReach = mean([lWristHip, rWristHip].filter(v => v !== null));
      const rawContraction = shoulderWidth !== null ? avgReach + shoulderWidth : avgReach;
      out.contraction = 1 - this.ranges.contraction.normalize(rawContraction);
    }

    // Verticality: head height relative to hip center
    const nose = landmarks[0];
    const lHip = landmarks[23], rHip = landmarks[24];
    if (nose.visibility > 0.3 && lHip.visibility > 0.3 && rHip.visibility > 0.3) {
      const hipMidY = (lHip.y + rHip.y) / 2;
      out.verticality = this.ranges.verticality.normalize(hipMidY - nose.y);
    }

    // Ankle spread
    if (landmarks[27].visibility > 0.3 && landmarks[28].visibility > 0.3) {
      out.ankleSpread = this.ranges.ankleSpread.normalize(Math.abs(landmarks[27].x - landmarks[28].x));
    }

    // Wrist spread
    if (landmarks[15].visibility > 0.3 && landmarks[16].visibility > 0.3) {
      out.wristSpread = this.ranges.wristSpread.normalize(Math.abs(landmarks[15].x - landmarks[16].x));
    }

    // === KINEMATIC PRIMITIVES ===

    if (!this.prevLandmarks) {
      this.prevLandmarks = landmarks;
      return out;
    }

    const leftVels = jointVelocities(landmarks, this.prevLandmarks, LEFT_JOINTS);
    const rightVels = jointVelocities(landmarks, this.prevLandmarks, RIGHT_JOINTS);
    const allVels = [...leftVels, ...rightVels];
    const frameVel = mean(allVels);

    let frameAccel = 0;
    if (this.prevPrevLandmarks) {
      const prevVels = jointVelocities(this.prevLandmarks, this.prevPrevLandmarks, BODY_JOINTS);
      if (prevVels.length > 0 && allVels.length > 0) {
        frameAccel = Math.abs(mean(allVels) - mean(prevVels));
      }
    }

    let frameJerk = 0;
    if (this.accelHistory.length > 0) {
      frameJerk = Math.abs(frameAccel - this.accelHistory[this.accelHistory.length - 1]);
    }

    this.prevPrevLandmarks = this.prevLandmarks;
    this.prevLandmarks = landmarks;

    this.velocityHistory.push(frameVel);
    this.accelHistory.push(frameAccel);
    this.jerkHistory.push(frameJerk);
    this.leftVelHistory.push(mean(leftVels));
    this.rightVelHistory.push(mean(rightVels));
    this.velDiffHistory.push(mean(leftVels) - mean(rightVels));

    for (const h of [this.velocityHistory, this.accelHistory, this.jerkHistory,
                      this.leftVelHistory, this.rightVelHistory, this.velDiffHistory]) {
      while (h.length > WINDOW) h.shift();
    }

    // Velocity
    out.velocity = this.ranges.velocity.normalize(mean(this.velocityHistory));

    // Jerkiness
    if (this.jerkHistory.length > 3) {
      out.jerkiness = this.ranges.jerk.normalize(mean(this.jerkHistory));
    }

    // Symmetry
    if (this.leftVelHistory.length > 5) {
      const mL = mean(this.leftVelHistory);
      const mR = mean(this.rightVelHistory);
      out.symmetry = Math.min(mL, mR) / Math.max(mL, mR, 0.0001);
    }

    // Coherence
    if (this.velDiffHistory.length > 5) {
      const meanDiff = mean(this.velDiffHistory);
      const variance = this.velDiffHistory.reduce((acc, d) => acc + (d - meanDiff) ** 2, 0) / this.velDiffHistory.length;
      out.coherence = 1 - this.ranges.coherence.normalize(Math.sqrt(variance));
    }

    return out;
  }

  /** Expose velocity history for relational computation (synchrony). */
  getVelocityHistory() {
    return this.velocityHistory;
  }
}

// --- Relational qualities (cross-body) ---
// Ported from Ralf's relational.ts. Pure function, no state.

const QUALITY_KEYS = ['velocity', 'jerkiness', 'symmetry', 'coherence', 'contraction', 'verticality', 'ankleSpread', 'wristSpread'];

/**
 * Compute relational qualities between two bodies.
 * @param {Object} q1 — qualities from body 1 (0-1 values)
 * @param {Object} q2 — qualities from body 2 (0-1 values)
 * @param {MovementDetector} det1 — detector 1 (for velocity history)
 * @param {MovementDetector} det2 — detector 2 (for velocity history)
 * @returns {{ synchrony: number, contrast: number, aggregate_energy: number }}
 */
export function computeRelational(q1, q2, det1, det2) {
  // Synchrony: Pearson correlation of velocity histories
  const h1 = det1.getVelocityHistory();
  const h2 = det2.getVelocityHistory();
  const synchrony = pearsonCorrelation(h1, h2);

  // Contrast: L2 distance of quality vectors, normalized to 0-1
  // Max possible L2 distance for N dimensions of [0,1] values = sqrt(N)
  let sumSq = 0;
  for (const k of QUALITY_KEYS) {
    const d = (q1[k] ?? 0) - (q2[k] ?? 0);
    sumSq += d * d;
  }
  const maxDist = Math.sqrt(QUALITY_KEYS.length);
  const contrast = Math.sqrt(sumSq) / maxDist;

  // Aggregate energy: mean velocity across both bodies
  const aggregate_energy = ((q1.velocity ?? 0) + (q2.velocity ?? 0)) / 2;

  return { synchrony, contrast, aggregate_energy };
}

function pearsonCorrelation(a, b) {
  const n = Math.min(a.length, b.length);
  if (n < 5) return 0;

  // Use the last n values from each
  const x = a.slice(-n);
  const y = b.slice(-n);

  let sumX = 0, sumY = 0;
  for (let i = 0; i < n; i++) { sumX += x[i]; sumY += y[i]; }
  const meanX = sumX / n, meanY = sumY / n;

  let num = 0, denomX = 0, denomY = 0;
  for (let i = 0; i < n; i++) {
    const dx = x[i] - meanX, dy = y[i] - meanY;
    num += dx * dy;
    denomX += dx * dx;
    denomY += dy * dy;
  }

  const denom = Math.sqrt(denomX * denomY);
  if (denom < 1e-10) return 0;

  // Pearson is -1 to 1; map to 0-1 (0 = opposite, 0.5 = uncorrelated, 1 = in sync)
  return (num / denom + 1) / 2;
}
