/**
 * @module help/RestartTourButton
 * @description Small, unobtrusive button that allows the user to restart the
 *   guided tour at any time. Placed in the app header. Hidden while the tour
 *   is already active.
 */

import React from 'react';
import { Compass } from 'lucide-react';
import { useHelp } from '../context';

const RestartTourButton = () => {
    const { isTourActive, startTour } = useHelp();

    if (isTourActive) return null;

    return (
        <button
            type="button"
            onClick={() => startTour(0)}
            className="flex items-center gap-1.5 px-3 py-2 sm:px-5 sm:py-3 bg-gradient-to-r from-violet-100 to-fuchsia-100 border-3 border-violet-300 rounded-xl hover:from-violet-200 hover:to-fuchsia-200 transition-all font-bold text-sm sm:text-base text-violet-800 shadow-md hover:shadow-lg"
            title="Restart guided tour"
            aria-label="Restart guided tour"
        >
            <Compass className="w-5 h-5" />
            <span className="hidden sm:inline">Restart Tour</span>
            <span className="sm:hidden">Tour</span>
        </button>
    );
};

export default RestartTourButton;
