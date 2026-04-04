/**
 * @module tour/TourProvider
 * @description Composes the tour engine, overlay, and card into a single
 *   provider component. Manages the highlight class on the current target
 *   element and renders the resume prompt when applicable.
 *
 * @param {Object} props
 * @param {React.RefObject} props.tourBridgeRef - Ref to the app data bridge.
 * @param {function} props.onTourStateChange - Callback to inform HelpProvider of tour state changes.
 */

import React, { useEffect, useRef } from 'react';
import useTourEngine from './useTourEngine';
import TourOverlay from './TourOverlay';
import TourCard from './TourCard';
import { Sparkles } from 'lucide-react';

const HIGHLIGHT_CLASS = 'help-onboarding-highlight';

const TourProvider = ({ tourBridgeRef, onTourStateChange }) => {
    const engine = useTourEngine({ tourBridgeRef });
    const highlightedRef = useRef(null);

    // Inform parent (HelpProvider) of tour state changes
    useEffect(() => {
        if (onTourStateChange) {
            onTourStateChange({
                isTourActive: engine.isActive,
                startTour: engine.startTour,
                endTour: engine.endTour,
            });
        }
    }, [engine.isActive, engine.startTour, engine.endTour, onTourStateChange]);

    // Manage highlight class on the target element
    useEffect(() => {
        const prev = highlightedRef.current;
        if (prev) {
            prev.classList.remove(HIGHLIGHT_CLASS);
        }
        highlightedRef.current = null;

        if (engine.isActive && engine.targetElement) {
            engine.targetElement.classList.add(HIGHLIGHT_CLASS);
            highlightedRef.current = engine.targetElement;

            // Scroll target into view
            engine.targetElement.scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
                inline: 'nearest',
            });
        }

        return () => {
            if (highlightedRef.current) {
                highlightedRef.current.classList.remove(HIGHLIGHT_CLASS);
            }
        };
    }, [engine.isActive, engine.targetElement]);

    // Cleanup highlight on unmount
    useEffect(() => {
        return () => {
            if (highlightedRef.current) {
                highlightedRef.current.classList.remove(HIGHLIGHT_CLASS);
            }
        };
    }, []);

    // Resume prompt
    if (engine.showResumePrompt && !engine.isActive) {
        return (
            <div className="fixed bottom-6 right-6 z-[90] max-w-sm w-[calc(100vw-2rem)]">
                <div className="bg-white border-2 border-indigo-200 rounded-2xl shadow-2xl overflow-hidden">
                    <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-4 py-3 flex items-center gap-2">
                        <Sparkles className="w-4 h-4" />
                        <span className="font-bold text-sm">Continue Tour?</span>
                    </div>
                    <div className="p-4">
                        <p className="text-sm text-gray-600 mb-4">
                            You have an unfinished tour. Would you like to pick up where you left off?
                        </p>
                        <div className="flex gap-2">
                            <button
                                type="button"
                                onClick={engine.dismissResume}
                                className="flex-1 px-3 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-semibold hover:bg-gray-50"
                            >
                                Start Over
                            </button>
                            <button
                                type="button"
                                onClick={engine.resumeTour}
                                className="flex-1 px-3 py-2 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 text-white text-sm font-semibold hover:shadow-lg transition-all"
                            >
                                Continue
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        );
    }

    if (!engine.isActive) return null;

    return (
        <>
            <TourOverlay isActive={engine.isActive} />
            <TourCard
                step={engine.currentStep}
                stepIndex={engine.stepIndex}
                totalSteps={engine.totalSteps}
                targetElement={engine.targetElement}
                onNext={engine.next}
                onForceNext={engine.forceNext}
                onBack={engine.back}
                onSkip={engine.endTour}
            />
        </>
    );
};

export default TourProvider;
