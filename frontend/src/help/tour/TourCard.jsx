/**
 * @module tour/TourCard
 * @description Floating tooltip card for the guided tour. Displays step title,
 *   body, optional tip callout, phase progress, and navigation buttons.
 *   Positioned absolutely using useTooltipPosition.
 *
 * @param {Object} props
 * @param {Object} props.step - Current tour step definition.
 * @param {number} props.stepIndex - Current step index (0-based).
 * @param {number} props.totalSteps - Total number of steps.
 * @param {HTMLElement|null} props.targetElement - The highlighted target element.
 * @param {function} props.onNext - Advance to next step (standard).
 * @param {function} props.onForceNext - Force-advance, skipping steps with unmet entry conditions.
 * @param {function} props.onBack - Go back one step.
 * @param {function} props.onSkip - End the tour immediately.
 */

import React from 'react';
import { Sparkles } from 'lucide-react';
import useTooltipPosition from './useTooltipPosition';
import { PHASES } from './tourConstants';

/**
 * Renders phase progress dots in the card header.
 *
 * @param {Object} props
 * @param {string} props.currentPhase - The active phase name.
 * @returns {JSX.Element}
 */
const PhaseProgress = ({ currentPhase }) => {
    const currentIndex = PHASES.indexOf(currentPhase);

    return (
        <div className="flex items-center gap-1.5 mt-2">
            {PHASES.map((phase, i) => (
                <React.Fragment key={phase}>
                    {i > 0 && (
                        <div
                            className={`h-px w-3 ${
                                i <= currentIndex ? 'bg-white/70' : 'bg-white/25'
                            }`}
                        />
                    )}
                    <div
                        className={`w-2 h-2 rounded-full ${
                            i < currentIndex
                                ? 'bg-white'
                                : i === currentIndex
                                  ? 'bg-white ring-2 ring-white/50'
                                  : 'bg-white/25'
                        }`}
                        title={phase}
                    />
                </React.Fragment>
            ))}
        </div>
    );
};

const TourCard = ({
    step,
    stepIndex,
    totalSteps,
    targetElement,
    onNext,
    onForceNext,
    onBack,
    onSkip,
}) => {
    const { top, left, arrowStyle, isCenter, setCardRef } =
        useTooltipPosition(targetElement, step?.placement, !!step);

    if (!step) return null;

    const isLast = stepIndex >= totalSteps - 1;
    const progress = ((stepIndex + 1) / totalSteps) * 100;

    // Every step gets a visible advance button — acts as an escape hatch so users
    // are never stuck waiting for an action/click they can't or don't want to perform.
    const isManual = step.advanceOn === 'manual';
    const showWaitingHint = step.advanceOn === 'action' || step.advanceOn === 'click';

    return (
        <div
            ref={setCardRef}
            className="tour-card fixed z-[90] pointer-events-auto max-w-md w-[calc(100vw-2rem)]"
            style={{
                top: `${top}px`,
                left: `${left}px`,
                ...(isCenter ? { transform: 'none' } : {}),
            }}
            role="dialog"
            aria-label={`Tour step ${stepIndex + 1}: ${step.title}`}
        >
            <div className="bg-white border-2 border-indigo-200 rounded-2xl shadow-2xl overflow-hidden">
                {/* Header */}
                <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-4 py-3">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <Sparkles className="w-4 h-4" />
                            <span className="px-2 py-0.5 bg-white/20 rounded-full text-xs font-semibold backdrop-blur-sm">
                                {step.phase}
                            </span>
                        </div>
                        <span className="text-xs font-semibold">
                            Step {stepIndex + 1} / {totalSteps}
                        </span>
                    </div>
                    {/* Progress bar */}
                    <div className="h-1 bg-white/20 rounded-full mt-2">
                        <div
                            className="h-1 bg-white rounded-full transition-all duration-500"
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                    {/* Phase dots */}
                    <PhaseProgress currentPhase={step.phase} />
                </div>

                {/* Body */}
                <div className="p-5">
                    <h3 className="font-bold text-lg text-gray-900 mb-2">
                        {step.title}
                    </h3>
                    <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-line">
                        {step.body}
                    </p>

                    {/* Tip callout */}
                    {step.tip && (
                        <div className="mt-3 p-3 bg-indigo-50 border border-indigo-200 rounded-xl text-xs text-indigo-800">
                            <span className="font-semibold">Tip:</span> {step.tip}
                        </div>
                    )}

                    {/* Waiting hint for click/action steps */}
                    {showWaitingHint && (
                        <div className="mt-3 p-2 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800 flex items-center gap-2">
                            <span className="inline-block w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
                            {step.advanceOn === 'click'
                                ? 'Click the highlighted element to continue...'
                                : 'Complete the action to continue...'}
                        </div>
                    )}

                    {/* Buttons */}
                    <div className="mt-4 flex items-center justify-between gap-2">
                        <div className="flex gap-2">
                            {step.canGoBack && stepIndex > 0 && (
                                <button
                                    type="button"
                                    onClick={onBack}
                                    className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-semibold hover:bg-gray-50 transition-colors"
                                >
                                    Back
                                </button>
                            )}
                            <button
                                type="button"
                                onClick={onSkip}
                                className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-semibold hover:bg-gray-50 transition-colors"
                            >
                                Skip Tour
                            </button>
                        </div>
                        <button
                            type="button"
                            onClick={isLast ? onSkip : isManual ? onNext : onForceNext}
                            className={isManual
                                ? 'px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-semibold hover:shadow-lg transition-all'
                                : 'px-4 py-2 rounded-lg border border-indigo-300 text-indigo-700 text-sm font-semibold hover:bg-indigo-50 transition-colors'
                            }
                        >
                            {isLast ? 'Finish' : isManual ? 'Next' : 'Skip Step'}
                        </button>
                    </div>
                </div>
            </div>

            {/* Arrow pointing to target */}
            {!isCenter && arrowStyle.display !== 'none' && (
                <div
                    className="tour-card-arrow absolute w-3 h-3 bg-white"
                    style={{
                        ...arrowStyle,
                        transform: 'rotate(45deg)',
                        position: 'absolute',
                    }}
                />
            )}
        </div>
    );
};

export default TourCard;
