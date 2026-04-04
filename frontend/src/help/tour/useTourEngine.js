/**
 * @module tour/useTourEngine
 * @description Core state machine hook for the interactive guided tour.
 *
 * Manages step tracking, advancement (manual / click / action / auto),
 * deviation recovery, and localStorage persistence for resume support.
 *
 * @param {Object} options
 * @param {React.RefObject} options.tourBridgeRef - Ref to the app data bridge
 * @returns {Object} Tour engine state and controls
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import tourSteps from './tourSteps';
import {
    TOUR_STORAGE_KEY,
    TOUR_PROGRESS_KEY,
    TOUR_VERSION,
    CONDITION_POLL_MS,
    TARGET_RETRY_MS,
    TARGET_RETRY_INTERVAL_MS,
} from './tourConstants';

/**
 * Determines whether the tour should auto-start on first visit.
 *
 * @returns {boolean} True if the tour has not been completed at this version.
 */
const shouldAutoStart = () => {
    try {
        const completed = localStorage.getItem(TOUR_STORAGE_KEY);
        return completed !== TOUR_VERSION;
    } catch {
        return true;
    }
};

/**
 * Reads the last saved step index for resume support.
 *
 * @returns {number|null} The saved step index or null if none.
 */
const getSavedProgress = () => {
    try {
        const raw = localStorage.getItem(TOUR_PROGRESS_KEY);
        if (raw == null) return null;
        const idx = parseInt(raw, 10);
        return Number.isFinite(idx) && idx >= 0 && idx < tourSteps.length ? idx : null;
    } catch {
        return null;
    }
};

/**
 * Persist the current step index to localStorage.
 *
 * @param {number} index - Current step index.
 */
const saveProgress = (index) => {
    try {
        localStorage.setItem(TOUR_PROGRESS_KEY, String(index));
    } catch {
        // Ignore storage errors in restricted browsers.
    }
};

/** Remove progress key from localStorage. */
const clearProgress = () => {
    try {
        localStorage.removeItem(TOUR_PROGRESS_KEY);
    } catch {
        // Ignore.
    }
};

/**
 * Mark tour as completed in localStorage.
 */
const markCompleted = () => {
    try {
        localStorage.setItem(TOUR_STORAGE_KEY, TOUR_VERSION);
        clearProgress();
    } catch {
        // Ignore.
    }
};

export default function useTourEngine({ tourBridgeRef }) {
    const [isActive, setIsActive] = useState(false);
    const [stepIndex, setStepIndex] = useState(0);
    const [showResumePrompt, setShowResumePrompt] = useState(false);
    const [targetElement, setTargetElement] = useState(null);

    const pollTimerRef = useRef(null);
    const retryTimerRef = useRef(null);
    const isActiveRef = useRef(false);

    /* eslint-disable react-hooks/refs */
    isActiveRef.current = isActive;
    /* eslint-enable react-hooks/refs */

    const currentStep = tourSteps[stepIndex] || null;
    const totalSteps = tourSteps.length;

    // ── Helpers ──────────────────────────────────────────

    const getBridge = useCallback(() => tourBridgeRef?.current || {}, [tourBridgeRef]);

    /** Stop all running polling timers. */
    const stopPolling = useCallback(() => {
        if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
        }
        if (retryTimerRef.current) {
            clearTimeout(retryTimerRef.current);
            retryTimerRef.current = null;
        }
    }, []);

    /**
     * Resolve the target DOM element for a given step.
     *
     * @param {Object} step - Tour step definition.
     * @returns {HTMLElement|null}
     */
    const resolveTarget = useCallback((step) => {
        if (!step) return null;
        if (step.targetFinder) {
            const el = step.targetFinder();
            if (el) return el;
        }
        if (step.targetSelector) {
            return document.querySelector(step.targetSelector);
        }
        return null;
    }, []);

    // ── Cleanup on unmount ──────────────────────────────
    useEffect(() => {
        return () => stopPolling();
    }, [stopPolling]);

    // ── Step index to ID lookup ─────────────────────────
    const getStepIndexById = useCallback((id) => {
        return tourSteps.findIndex((s) => s.id === id);
    }, []);

    // ── Navigation ──────────────────────────────────────

    /**
     * Move to a specific step index, running onExit/onEnter side effects.
     *
     * @param {number} nextIndex - The step index to navigate to.
     */
    const goToStep = useCallback((nextIndex) => {
        if (nextIndex < 0 || nextIndex >= tourSteps.length) return;

        stopPolling();

        // onExit for the current step
        const current = tourSteps[stepIndex];
        if (current?.onExit) {
            try { current.onExit(getBridge()); } catch { /* guard */ }
        }

        setStepIndex(nextIndex);
        saveProgress(nextIndex);

        // onEnter for the next step
        const next = tourSteps[nextIndex];
        if (next?.onEnter) {
            try { next.onEnter(getBridge()); } catch { /* guard */ }
        }
    }, [stepIndex, stopPolling, getBridge]);

    /** Advance to the next step. If on the last step, complete the tour. */
    const next = useCallback(() => {
        if (stepIndex >= tourSteps.length - 1) {
            // Tour complete
            stopPolling();
            markCompleted();
            setIsActive(false);
            setTargetElement(null);
            return;
        }
        goToStep(stepIndex + 1);
    }, [stepIndex, goToStep, stopPolling]);

    /** Go back one step (if allowed). */
    const back = useCallback(() => {
        if (stepIndex > 0) {
            goToStep(stepIndex - 1);
        }
    }, [stepIndex, goToStep]);

    /** End the tour immediately (skip). */
    const endTour = useCallback(() => {
        stopPolling();
        markCompleted();
        setIsActive(false);
        setTargetElement(null);
    }, [stopPolling]);

    /**
     * Force-advance to the next viable step, skipping any steps whose
     * entryCondition currently fails. This is the "escape hatch" that
     * guarantees the user is never stuck on an action/click step.
     */
    const forceNext = useCallback(() => {
        stopPolling();

        const bridge = getBridge();
        let nextIdx = stepIndex + 1;

        // Walk forward until we find a step with no entryCondition or a passing one
        while (nextIdx < tourSteps.length) {
            const step = tourSteps[nextIdx];
            if (!step.entryCondition || step.entryCondition(bridge)) {
                break;
            }
            nextIdx++;
        }

        if (nextIdx >= tourSteps.length) {
            // No viable step remains — complete the tour
            markCompleted();
            setIsActive(false);
            setTargetElement(null);
            return;
        }

        goToStep(nextIdx);
    }, [stepIndex, stopPolling, getBridge, goToStep]);

    /** Start the tour from a given step index (default 0). */
    const startTour = useCallback((fromIndex = 0) => {
        clearProgress();
        setStepIndex(fromIndex);
        saveProgress(fromIndex);
        setIsActive(true);
        setShowResumePrompt(false);

        const step = tourSteps[fromIndex];
        if (step?.onEnter) {
            try { step.onEnter(tourBridgeRef?.current || {}); } catch { /* guard */ }
        }
    }, [tourBridgeRef]);

    // ── Auto-start / Resume logic ───────────────────────
    useEffect(() => {
        if (isActive) return;
        if (!shouldAutoStart()) return;

        const saved = getSavedProgress();
        if (saved != null && saved > 0) {
            setShowResumePrompt(true);
        } else {
            // Auto-start from step 0 after a short delay (let app mount)
            const timer = setTimeout(() => {
                if (!isActiveRef.current) {
                    startTour(0);
                }
            }, 800);
            return () => clearTimeout(timer);
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    /** Resume from saved progress (called by UI). */
    const resumeTour = useCallback(() => {
        const saved = getSavedProgress();
        startTour(saved || 0);
    }, [startTour]);

    /** Dismiss resume prompt and start fresh. */
    const dismissResume = useCallback(() => {
        setShowResumePrompt(false);
        startTour(0);
    }, [startTour]);

    // ── Target element resolution + retry ───────────────
    useEffect(() => {
        if (!isActive || !currentStep) {
            setTargetElement(null);
            return;
        }

        // Immediate attempt
        const el = resolveTarget(currentStep);
        if (el) {
            setTargetElement(el);
            return;
        }

        // Retry loop for up to TARGET_RETRY_MS
        setTargetElement(null);
        const startTime = Date.now();
        const interval = setInterval(() => {
            const found = resolveTarget(currentStep);
            if (found) {
                setTargetElement(found);
                clearInterval(interval);
            } else if (Date.now() - startTime > TARGET_RETRY_MS) {
                clearInterval(interval);
                // Fallback: no target (card goes to center/fixed position)
            }
        }, TARGET_RETRY_INTERVAL_MS);

        retryTimerRef.current = interval;
        return () => clearInterval(interval);
    }, [isActive, currentStep, stepIndex, resolveTarget]);

    // ── Deviation recovery + action polling ─────────────
    useEffect(() => {
        if (!isActive || !currentStep) return;

        const poll = () => {
            const bridge = getBridge();

            // Check entryCondition — if it fails, revert to fallback step
            if (currentStep.entryCondition && !currentStep.entryCondition(bridge)) {
                const fallbackId = currentStep.fallbackStepId;
                if (fallbackId) {
                    const fallbackIdx = getStepIndexById(fallbackId);
                    if (fallbackIdx >= 0) {
                        goToStep(fallbackIdx);
                        return;
                    }
                }
            }

            // Check advanceCondition for 'action' type steps
            if (currentStep.advanceOn === 'action' && currentStep.advanceCondition) {
                if (currentStep.advanceCondition(bridge)) {
                    next();
                }
            }
        };

        pollTimerRef.current = setInterval(poll, CONDITION_POLL_MS);
        return () => {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
        };
    }, [isActive, currentStep, stepIndex, getBridge, getStepIndexById, goToStep, next]);

    // ── Click advancement (for 'click' type steps) ──────
    useEffect(() => {
        if (!isActive || !currentStep || currentStep.advanceOn !== 'click' || !targetElement) {
            return;
        }

        const handler = () => {
            // Small delay so the click's own handler runs first
            setTimeout(() => next(), 50);
        };

        targetElement.addEventListener('click', handler, { once: true });
        return () => targetElement.removeEventListener('click', handler);
    }, [isActive, currentStep, targetElement, next]);

    // ── Auto advancement ────────────────────────────────
    useEffect(() => {
        if (!isActive || !currentStep || currentStep.advanceOn !== 'auto') return;
        const timer = setTimeout(() => next(), 400);
        return () => clearTimeout(timer);
    }, [isActive, currentStep, next]);

    return {
        isActive,
        stepIndex,
        currentStep,
        totalSteps,
        targetElement,
        showResumePrompt,
        next,
        forceNext,
        back,
        endTour,
        startTour,
        resumeTour,
        dismissResume,
    };
}
