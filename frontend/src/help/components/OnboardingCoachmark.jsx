import React from 'react';
import { Sparkles } from 'lucide-react';

const OnboardingCoachmark = ({
    isOpen,
    step,
    stepIndex,
    totalSteps,
    onNext,
    onBack,
    onSkip,
    onOpenTopic,
}) => {
    if (!isOpen || !step) return null;

    const isLast = stepIndex >= totalSteps - 1;

    return (
        <div className="fixed bottom-6 right-6 z-[90] max-w-md w-[calc(100vw-2rem)]">
            <div className="bg-white border-2 border-indigo-200 rounded-2xl shadow-2xl overflow-hidden">
                <div className="bg-gradient-to-r from-indigo-600 to-blue-600 text-white px-4 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2 font-bold text-sm">
                        <Sparkles className="w-4 h-4" />
                        Quick Orientation
                    </div>
                    <div className="text-xs font-semibold">
                        Step {stepIndex + 1} / {totalSteps}
                    </div>
                </div>
                <div className="p-4">
                    <h4 className="font-bold text-gray-900 mb-1">{step.title}</h4>
                    <p className="text-sm text-gray-600 leading-6">{step.description}</p>
                    <div className="mt-4 flex flex-wrap gap-2">
                        {stepIndex > 0 && (
                            <button
                                type="button"
                                onClick={onBack}
                                className="px-3 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-semibold hover:bg-gray-50"
                            >
                                Back
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={onSkip}
                            className="px-3 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm font-semibold hover:bg-gray-50"
                        >
                            Skip
                        </button>
                        <button
                            type="button"
                            onClick={onOpenTopic}
                            className="px-3 py-2 rounded-lg border border-indigo-300 text-indigo-700 text-sm font-semibold hover:bg-indigo-50"
                        >
                            Open Full Help
                        </button>
                        <button
                            type="button"
                            onClick={onNext}
                            className="px-3 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700"
                        >
                            {isLast ? 'Done' : 'Next'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default OnboardingCoachmark;
