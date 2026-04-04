/**
 * @module tour/TourOverlay
 * @description Semi-transparent backdrop overlay rendered behind the tour card
 *   and above the app content. Highlighted target elements punch through via
 *   z-index layering (the `.help-onboarding-highlight` class).
 *
 * @param {Object} props
 * @param {boolean} props.isActive - Whether the tour is currently running.
 */

import React from 'react';

const TourOverlay = ({ isActive }) => {
    if (!isActive) return null;

    return (
        <div
            className="tour-overlay fixed inset-0 z-[80] bg-black/45 transition-opacity duration-250 pointer-events-none"
            aria-hidden="true"
        />
    );
};

export default TourOverlay;
