import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import HelpModal from './components/HelpModal';
import OnboardingCoachmark from './components/OnboardingCoachmark';
import { getGlossaryTermById, getTopicById, onboardingConfig } from './content';

const ONBOARDING_HIGHLIGHT_CLASS = 'help-onboarding-highlight';

const HelpContext = createContext(null);

const topicByTargetId = {
    'tab-workers': 'workers.overview',
    'tab-shifts': 'shifts.overview',
    'tab-constraints': 'constraints.logic',
    'tab-schedule': 'schedule.interpretation',
    'btn-run-solver': 'schedule.interpretation',
    'btn-export-state': 'data.management',
    'btn-export-result': 'data.management',
};

export const HelpProvider = ({ children }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [currentTopicId, setCurrentTopicId] = useState(null);
    const [helpContext, setHelpContext] = useState({});
    const [showOnboarding, setShowOnboarding] = useState(false);
    const [onboardingStepIndex, setOnboardingStepIndex] = useState(0);
    const highlightedElementRef = useRef(null);

    const onboardingSteps = onboardingConfig.steps || [];
    const onboardingStorageKey = onboardingConfig.storageKey || 'shiftapp:onboarding:v1';
    const onboardingVersion = onboardingConfig.version || '1.0';
    const currentOnboardingStep = onboardingSteps[onboardingStepIndex] || null;

    const openHelp = useCallback((topicId, context = {}) => {
        const topic = getTopicById(topicId);
        if (!topic) return;
        setHelpContext(context);
        setCurrentTopicId(topicId);
        setIsOpen(true);
    }, []);

    const closeHelp = useCallback(() => {
        setIsOpen(false);
    }, []);

    const getGlossaryTerm = useCallback((termId) => getGlossaryTermById(termId), []);

    const closeOnboarding = useCallback(() => {
        setShowOnboarding(false);
        try {
            localStorage.setItem(onboardingStorageKey, onboardingVersion);
        } catch (err) {
            // Ignore storage errors in restricted browsers.
        }
    }, [onboardingStorageKey, onboardingVersion]);

    const nextOnboarding = useCallback(() => {
        setOnboardingStepIndex((prev) => {
            if (prev >= onboardingSteps.length - 1) {
                closeOnboarding();
                return prev;
            }
            return prev + 1;
        });
    }, [closeOnboarding, onboardingSteps.length]);

    const prevOnboarding = useCallback(() => {
        setOnboardingStepIndex((prev) => Math.max(0, prev - 1));
    }, []);

    const openHelpForCurrentOnboardingStep = useCallback(() => {
        if (!currentOnboardingStep) return;
        const fallbackTopic = 'data.management';
        const topicId = topicByTargetId[currentOnboardingStep.targetId] || fallbackTopic;
        openHelp(topicId, { source: 'onboarding' });
    }, [currentOnboardingStep, openHelp]);

    useEffect(() => {
        if (onboardingSteps.length === 0) return;
        try {
            const seenVersion = localStorage.getItem(onboardingStorageKey);
            if (seenVersion !== onboardingVersion) {
                setShowOnboarding(true);
                setOnboardingStepIndex(0);
            }
        } catch (err) {
            setShowOnboarding(true);
            setOnboardingStepIndex(0);
        }
    }, [onboardingSteps.length, onboardingStorageKey, onboardingVersion]);

    useEffect(() => {
        const previous = highlightedElementRef.current;
        if (previous) {
            previous.classList.remove(ONBOARDING_HIGHLIGHT_CLASS);
        }
        highlightedElementRef.current = null;

        if (!showOnboarding || !currentOnboardingStep?.targetId) return;

        const target = document.getElementById(currentOnboardingStep.targetId);
        if (!target) return;

        target.classList.add(ONBOARDING_HIGHLIGHT_CLASS);
        highlightedElementRef.current = target;
        target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });

        return () => {
            target.classList.remove(ONBOARDING_HIGHLIGHT_CLASS);
        };
    }, [showOnboarding, currentOnboardingStep]);

    const value = useMemo(() => ({
        openHelp,
        closeHelp,
        isOpen,
        currentTopicId,
        currentTopic: getTopicById(currentTopicId),
        getGlossaryTerm,
        helpContext,
    }), [openHelp, closeHelp, isOpen, currentTopicId, getGlossaryTerm, helpContext]);

    return (
        <HelpContext.Provider value={value}>
            {children}
            <HelpModal
                isOpen={isOpen}
                onClose={closeHelp}
                topic={getTopicById(currentTopicId)}
                getGlossaryTerm={getGlossaryTerm}
            />
            <OnboardingCoachmark
                isOpen={showOnboarding}
                step={currentOnboardingStep}
                stepIndex={onboardingStepIndex}
                totalSteps={onboardingSteps.length}
                onNext={nextOnboarding}
                onBack={prevOnboarding}
                onSkip={closeOnboarding}
                onOpenTopic={openHelpForCurrentOnboardingStep}
            />
        </HelpContext.Provider>
    );
};

export const useHelp = () => {
    const context = useContext(HelpContext);
    if (!context) {
        return {
            openHelp: () => {},
            closeHelp: () => {},
            isOpen: false,
            currentTopicId: null,
            currentTopic: null,
            getGlossaryTerm: () => null,
            helpContext: {},
        };
    }
    return context;
};
