import React, { useCallback, useMemo, useRef, useState } from 'react';
import HelpModal from './components/HelpModal';
import TourProvider from './tour/TourProvider';
import { getGlossaryTermById, getTopicById } from './content';
import { HelpContext } from './context';

/**
 * @param {Object} props
 * @param {React.ReactNode} props.children
 * @param {React.RefObject} props.tourBridgeRef - Ref to the app-level data bridge for the tour.
 */
export const HelpProvider = ({ children, tourBridgeRef }) => {
    const [isOpen, setIsOpen] = useState(false);
    const [currentTopicId, setCurrentTopicId] = useState(null);
    const [helpContext, setHelpContext] = useState({});

    // Tour state exposed through context (populated by TourProvider callback)
    const tourStateRef = useRef({ isTourActive: false, startTour: () => {}, endTour: () => {} });
    const [tourActive, setTourActive] = useState(false);

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

    /** Called by TourProvider whenever tour state changes. */
    const handleTourStateChange = useCallback((state) => {
        tourStateRef.current = state;
        setTourActive(state.isTourActive);
    }, []);

    const value = useMemo(() => ({
        openHelp,
        closeHelp,
        isOpen,
        currentTopicId,
        currentTopic: getTopicById(currentTopicId),
        getGlossaryTerm,
        helpContext,
        isTourActive: tourActive,
        startTour: (...args) => tourStateRef.current.startTour(...args),
        endTour: () => tourStateRef.current.endTour(),
    }), [openHelp, closeHelp, isOpen, currentTopicId, getGlossaryTerm, helpContext, tourActive]);

    return (
        <HelpContext.Provider value={value}>
            {children}
            <HelpModal
                isOpen={isOpen}
                onClose={closeHelp}
                topic={getTopicById(currentTopicId)}
                getGlossaryTerm={getGlossaryTerm}
            />
            <TourProvider
                tourBridgeRef={tourBridgeRef}
                onTourStateChange={handleTourStateChange}
            />
        </HelpContext.Provider>
    );
};
