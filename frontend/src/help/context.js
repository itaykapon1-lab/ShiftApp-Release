import { createContext, useContext } from 'react';

export const HelpContext = createContext(null);

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
            isTourActive: false,
            startTour: () => {},
            endTour: () => {},
        };
    }
    return context;
};
