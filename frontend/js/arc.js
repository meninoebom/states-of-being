/**
 * Arc engine — data-driven phase sequencer for Song Blender.
 *
 * An arc is an ordered list of phases. Each phase defines which audio categories
 * are available and how long it lasts. Movement engagement stretches/compresses
 * phase durations. The AWAIT phase waits for movement before starting.
 *
 * The arc is config, not code — swap DEFAULT_ARC to change the entire experience.
 */

export const DEFAULT_ARC = {
  phases: [
    { id: 'await',     categories: ['texture'],                                                                     duration: null, trigger: 'movement' },
    { id: 'emerge',    categories: ['texture', 'bass'],                                                             duration: [40, 50] },
    { id: 'build',     categories: ['texture', 'bass', 'foundation', 'harmonic_bed'],                               duration: [60, 80] },
    { id: 'peak',      categories: ['texture', 'bass', 'foundation', 'harmonic_bed', 'groove', 'hook', 'accent'],   duration: [50, 65] },
    { id: 'breakdown', categories: ['texture', 'harmonic_bed'],                                                     duration: [25, 35] },
    { id: 'resolve',   categories: ['texture', 'bass', 'foundation', 'harmonic_bed', 'groove', 'hook'],             duration: [50, 65] },
  ],
  sectionMap: {
    emerge: 'intro',
    build: 'verse',
    peak: 'chorus',
    breakdown: 'bridge',
    resolve: 'outro',
  },
};

const ENGAGEMENT_WINDOW = 300; // frames (~10s at 30fps)
const MOVEMENT_TRIGGER_THRESHOLD = 0.15;
const MOVEMENT_TRIGGER_SUSTAIN = 1.0; // seconds above threshold to trigger
const EARLY_BREAKDOWN_STILLNESS = 5.0; // seconds of near-zero velocity in PEAK

export class ArcEngine {
  constructor(config = DEFAULT_ARC) {
    this.config = config;
    this.phaseIndex = 0;
    this.phaseElapsed = 0;
    this.complete = false;

    // Engagement tracking — circular buffer for O(1) push
    this._velocityBuf = new Float32Array(ENGAGEMENT_WINDOW);
    this._velocityIdx = 0;
    this._velocityCount = 0;
    this._velocitySum = 0;
    this._cachedEngagement = 0.5;

    this.sustainedMovementTime = 0;
    this.stillnessTime = 0;

    // Callbacks
    this.onPhaseChange = null; // (phase) => void
    this.onComplete = null;    // () => void
  }

  /** Current phase config. */
  getCurrentPhase() {
    const phase = this.config.phases[this.phaseIndex];
    if (!phase) return null;

    const duration = this._effectiveDuration();
    const progress = duration ? Math.min(1, this.phaseElapsed / duration) : 0;
    const section = this.config.sectionMap[phase.id] || null;

    return {
      id: phase.id,
      categories: phase.categories,
      progress,
      section,
      index: this.phaseIndex,
      totalPhases: this.config.phases.length,
    };
  }

  /**
   * Call each frame. Advances phase state based on time and movement.
   * @param {number} dt — seconds since last frame
   * @param {number} velocity — current body velocity (0-1), or 0 if no body
   */
  update(dt, velocity) {
    if (this.complete) return;

    // Track engagement via circular buffer (O(1) per frame)
    const idx = this._velocityIdx % ENGAGEMENT_WINDOW;
    if (this._velocityCount >= ENGAGEMENT_WINDOW) {
      this._velocitySum -= this._velocityBuf[idx];
    }
    this._velocityBuf[idx] = velocity;
    this._velocitySum += velocity;
    this._velocityIdx++;
    this._velocityCount = Math.min(this._velocityCount + 1, ENGAGEMENT_WINDOW);
    this._cachedEngagement = this._velocityCount > 0 ? this._velocitySum / this._velocityCount : 0.5;

    const phase = this.config.phases[this.phaseIndex];
    if (!phase) return;

    // AWAIT: wait for sustained movement
    if (phase.trigger === 'movement') {
      if (velocity > MOVEMENT_TRIGGER_THRESHOLD) {
        this.sustainedMovementTime += dt;
      } else {
        this.sustainedMovementTime = Math.max(0, this.sustainedMovementTime - dt * 2);
      }
      if (this.sustainedMovementTime >= MOVEMENT_TRIGGER_SUSTAIN) {
        this._advancePhase();
      }
      return;
    }

    // Timed phases
    this.phaseElapsed += dt;

    // Early BREAKDOWN trigger: prolonged stillness during PEAK
    if (phase.id === 'peak') {
      if (velocity < 0.05) {
        this.stillnessTime += dt;
      } else {
        this.stillnessTime = 0;
      }
      if (this.stillnessTime >= EARLY_BREAKDOWN_STILLNESS) {
        this._advancePhase();
        return;
      }
    }

    const duration = this._effectiveDuration();
    if (duration && this.phaseElapsed >= duration) {
      this._advancePhase();
    }
  }

  /** Effective duration of current phase, adjusted by engagement. */
  _effectiveDuration() {
    const phase = this.config.phases[this.phaseIndex];
    if (!phase || !phase.duration) return null;

    const [min, max] = phase.duration;
    const mid = (min + max) / 2;
    const engagement = Math.max(0, Math.min(1, this._engagementLevel()));

    // High engagement → stretch toward max, low → compress toward min
    // engagement 0.5 = mid, 1.0 = max, 0.0 = min
    return min + (max - min) * engagement;
  }

  /** Rolling average of velocity (0-1), cached from update(). */
  _engagementLevel() {
    return this._cachedEngagement;
  }

  _advancePhase() {
    this.phaseIndex++;
    this.phaseElapsed = 0;
    this.sustainedMovementTime = 0;
    this.stillnessTime = 0;

    if (this.phaseIndex >= this.config.phases.length) {
      this.complete = true;
      if (this.onComplete) this.onComplete();
      return;
    }

    if (this.onPhaseChange) {
      this.onPhaseChange(this.config.phases[this.phaseIndex]);
    }
  }

  reset() {
    this.phaseIndex = 0;
    this.phaseElapsed = 0;
    this.complete = false;
    this._velocityBuf.fill(0);
    this._velocityIdx = 0;
    this._velocityCount = 0;
    this._velocitySum = 0;
    this._cachedEngagement = 0.5;
    this.sustainedMovementTime = 0;
    this.stillnessTime = 0;
  }

  isComplete() {
    return this.complete;
  }
}
