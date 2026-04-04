/**
 * @module tour/useTooltipPosition
 * @description Calculates tooltip position relative to a target element.
 *
 * Uses getBoundingClientRect for the target and the card, then clamps to
 * viewport bounds. Recalculates on scroll, resize, and element mutations.
 *
 * @param {HTMLElement|null} targetElement - The DOM element to point at.
 * @param {string} preferredPlacement - Desired placement (top|bottom|left|right|center).
 * @param {boolean} isActive - Whether the tour is currently active.
 * @returns {Object} { top, left, placement, arrowStyle }
 */

import { useState, useEffect, useCallback, useRef } from 'react';

/** Padding from viewport edges (px). */
const VIEWPORT_PADDING = 16;

/** Gap between target and card (px). */
const TARGET_GAP = 12;

/** Card estimated dimensions for initial calculation. */
const CARD_WIDTH = 400;
const CARD_HEIGHT = 300;

export default function useTooltipPosition(targetElement, preferredPlacement, isActive) {
    const [position, setPosition] = useState({
        top: 0,
        left: 0,
        placement: preferredPlacement || 'bottom',
        arrowStyle: {},
        isCenter: !targetElement,
    });

    const cardRef = useRef(null);

    const calculate = useCallback(() => {
        // Center placement or no target — center the card on screen
        if (!targetElement || preferredPlacement === 'center') {
            setPosition({
                top: Math.max(VIEWPORT_PADDING, (window.innerHeight - CARD_HEIGHT) / 2),
                left: Math.max(VIEWPORT_PADDING, (window.innerWidth - Math.min(CARD_WIDTH, window.innerWidth - 2 * VIEWPORT_PADDING)) / 2),
                placement: 'center',
                arrowStyle: { display: 'none' },
                isCenter: true,
            });
            return;
        }

        const targetRect = targetElement.getBoundingClientRect();
        const cardEl = cardRef.current;
        const cardWidth = cardEl ? cardEl.offsetWidth : CARD_WIDTH;
        const cardHeight = cardEl ? cardEl.offsetHeight : CARD_HEIGHT;

        const vw = window.innerWidth;
        const vh = window.innerHeight;

        /**
         * Try each placement and return { top, left, arrowStyle } if it fits.
         *
         * @param {string} p - Placement to try.
         * @returns {Object|null} Position object or null if it doesn't fit.
         */
        const tryPlacement = (p) => {
            let top, left;
            const arrowStyle = {};

            switch (p) {
                case 'bottom':
                    top = targetRect.bottom + TARGET_GAP;
                    left = targetRect.left + targetRect.width / 2 - cardWidth / 2;
                    arrowStyle.top = -6;
                    arrowStyle.left = cardWidth / 2 - 6;
                    arrowStyle.borderRight = '2px solid rgb(199 210 254)';
                    arrowStyle.borderBottom = '2px solid rgb(199 210 254)';
                    arrowStyle.borderTop = 'none';
                    arrowStyle.borderLeft = 'none';
                    break;
                case 'top':
                    top = targetRect.top - cardHeight - TARGET_GAP;
                    left = targetRect.left + targetRect.width / 2 - cardWidth / 2;
                    arrowStyle.bottom = -6;
                    arrowStyle.left = cardWidth / 2 - 6;
                    arrowStyle.borderLeft = '2px solid rgb(199 210 254)';
                    arrowStyle.borderTop = '2px solid rgb(199 210 254)';
                    arrowStyle.borderRight = 'none';
                    arrowStyle.borderBottom = 'none';
                    break;
                case 'right':
                    top = targetRect.top + targetRect.height / 2 - cardHeight / 2;
                    left = targetRect.right + TARGET_GAP;
                    arrowStyle.top = cardHeight / 2 - 6;
                    arrowStyle.left = -6;
                    arrowStyle.borderTop = '2px solid rgb(199 210 254)';
                    arrowStyle.borderRight = '2px solid rgb(199 210 254)';
                    arrowStyle.borderBottom = 'none';
                    arrowStyle.borderLeft = 'none';
                    break;
                case 'left':
                    top = targetRect.top + targetRect.height / 2 - cardHeight / 2;
                    left = targetRect.left - cardWidth - TARGET_GAP;
                    arrowStyle.top = cardHeight / 2 - 6;
                    arrowStyle.right = -6;
                    arrowStyle.borderBottom = '2px solid rgb(199 210 254)';
                    arrowStyle.borderLeft = '2px solid rgb(199 210 254)';
                    arrowStyle.borderTop = 'none';
                    arrowStyle.borderRight = 'none';
                    break;
                default:
                    return null;
            }

            // Check if it fits in viewport
            if (top < VIEWPORT_PADDING || top + cardHeight > vh - VIEWPORT_PADDING) return null;
            if (left < VIEWPORT_PADDING || left + cardWidth > vw - VIEWPORT_PADDING) return null;

            return { top, left, arrowStyle };
        };

        // Try preferred placement first, then fallback order
        const fallbackOrder = {
            bottom: ['bottom', 'top', 'right', 'left'],
            top: ['top', 'bottom', 'right', 'left'],
            right: ['right', 'left', 'bottom', 'top'],
            left: ['left', 'right', 'bottom', 'top'],
        };

        const order = fallbackOrder[preferredPlacement] || fallbackOrder.bottom;
        let result = null;
        let finalPlacement = preferredPlacement;

        for (const p of order) {
            result = tryPlacement(p);
            if (result) {
                finalPlacement = p;
                break;
            }
        }

        if (!result) {
            // Absolute fallback: below target, clamped
            result = {
                top: Math.min(
                    Math.max(VIEWPORT_PADDING, targetRect.bottom + TARGET_GAP),
                    vh - cardHeight - VIEWPORT_PADDING
                ),
                left: Math.min(
                    Math.max(VIEWPORT_PADDING, targetRect.left),
                    vw - cardWidth - VIEWPORT_PADDING
                ),
                arrowStyle: { display: 'none' },
            };
            finalPlacement = 'bottom';
        }

        // Clamp left/top to viewport bounds
        result.left = Math.max(VIEWPORT_PADDING, Math.min(result.left, vw - cardWidth - VIEWPORT_PADDING));
        result.top = Math.max(VIEWPORT_PADDING, Math.min(result.top, vh - cardHeight - VIEWPORT_PADDING));

        setPosition({
            top: result.top,
            left: result.left,
            placement: finalPlacement,
            arrowStyle: result.arrowStyle,
            isCenter: false,
        });
    }, [targetElement, preferredPlacement]);

    // Recalculate on scroll/resize
    useEffect(() => {
        if (!isActive) return;

        /* eslint-disable react-hooks/set-state-in-effect */
        calculate();
        /* eslint-enable react-hooks/set-state-in-effect */

        const handleUpdate = () => calculate();

        window.addEventListener('scroll', handleUpdate, { passive: true, capture: true });
        window.addEventListener('resize', handleUpdate, { passive: true });

        // ResizeObserver for target element changes
        let observer;
        if (targetElement && typeof ResizeObserver !== 'undefined') {
            observer = new ResizeObserver(handleUpdate);
            observer.observe(targetElement);
        }

        return () => {
            window.removeEventListener('scroll', handleUpdate, { capture: true });
            window.removeEventListener('resize', handleUpdate);
            if (observer) observer.disconnect();
        };
    }, [isActive, calculate, targetElement]);

    // Recalculate when cardRef mounts (to get real dimensions)
    const setCardRef = useCallback((node) => {
        cardRef.current = node;
        if (node) calculate();
    }, [calculate]);

    return { ...position, setCardRef };
}
