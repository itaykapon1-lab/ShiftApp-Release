/**
 * @module tour/tourConstants
 * @description Shared constants for the interactive guided tour system.
 */

/** localStorage key for persisting tour completion and progress. */
export const TOUR_STORAGE_KEY = 'shiftapp:tour:v1';

/** localStorage key for storing the last completed step index (resume support). */
export const TOUR_PROGRESS_KEY = 'shiftapp:tour:progress';

/** Version string — bump to re-show the tour after major changes. */
export const TOUR_VERSION = '1.0';

/** Polling interval (ms) for advanceCondition checks. */
export const CONDITION_POLL_MS = 300;

/** Max wait time (ms) for a target element to appear before falling back. */
export const TARGET_RETRY_MS = 2000;

/** Retry interval (ms) when waiting for a target element. */
export const TARGET_RETRY_INTERVAL_MS = 100;

/** Animation duration (ms) for card enter/exit. */
export const CARD_ANIMATION_MS = 250;

/** Phase names used for grouping steps and progress display. */
export const PHASES = ['WELCOME', 'WORKERS', 'SHIFTS', 'CONSTRAINTS', 'SOLVER'];
