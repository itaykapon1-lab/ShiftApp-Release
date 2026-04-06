// ========================================
// SCORE INDICATOR - Visual score badges
// ========================================

import React, { useEffect, useRef, useState } from 'react';
import { formatDiagnosticMessage } from '../../../utils/displayFormatting';
import useTooltipPosition from '../../../help/tour/useTooltipPosition';

/**
 * ScoreIndicator Component
 *
 * Displays a score badge with color coding:
 * - Green for positive scores (+X)
 * - Red for negative scores (-X) or global violations
 * - Gray for zero scores
 *
 * Shows a tooltip on hover with score breakdown details.
 *
 * Props:
 * - score: Number - the score value
 * - breakdown: String - optional breakdown explanation
 * - globalViolations: Array - optional global violations mapped to this assignment
 */
const ScoreIndicator = ({ score, breakdown, globalViolations = [], employees = [] }) => {
    const [showTooltip, setShowTooltip] = useState(false);
    const wrapperRef = useRef(null);
    const triggerRef = useRef(null);

    const normalizedGlobalViolations = Array.isArray(globalViolations)
        ? globalViolations
            .map((violation) => {
                if (!violation) return '';
                if (typeof violation === 'string') return violation;
                return violation.description || '';
            })
            .filter(Boolean)
        : [];

    const hasGlobalViolations = normalizedGlobalViolations.length > 0;

    // Determine color based on score and global violations
    const isPositive = !hasGlobalViolations && score > 0;
    const isNegative = hasGlobalViolations || score < 0;

    const bgColor = isPositive
        ? 'bg-green-100 border-green-300'
        : isNegative
            ? 'bg-red-100 border-red-300'
            : 'bg-gray-100 border-gray-300';

    const textColor = isPositive
        ? 'text-green-700'
        : isNegative
            ? 'text-red-700'
            : 'text-gray-500';

    const formatScore = (value) => {
        if (value > 0) return `+${value}`;
        return String(value);
    };

    const tooltipLines = [];

    if (breakdown && breakdown !== '-') {
        tooltipLines.push(formatDiagnosticMessage(String(breakdown), employees));
    }

    if (hasGlobalViolations) {
        normalizedGlobalViolations.forEach((description) => {
            tooltipLines.push(`Global: ${formatDiagnosticMessage(description, employees)}`);
        });
    }

    const showBreakdownTooltip = showTooltip && tooltipLines.length > 0;
    const { top, left, setCardRef } = useTooltipPosition(triggerRef.current, 'top', showBreakdownTooltip);

    useEffect(() => {
        if (!showBreakdownTooltip) return;

        const onClickOutside = (event) => {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
                setShowTooltip(false);
            }
        };

        const onKeyDown = (event) => {
            if (event.key === 'Escape') {
                setShowTooltip(false);
            }
        };

        document.addEventListener('mousedown', onClickOutside);
        document.addEventListener('keydown', onKeyDown);

        return () => {
            document.removeEventListener('mousedown', onClickOutside);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [showBreakdownTooltip]);

    return (
        <div
            ref={wrapperRef}
            className="relative inline-block"
            onMouseEnter={() => setShowTooltip(true)}
            onMouseLeave={() => setShowTooltip(false)}
        >
            <button
                ref={triggerRef}
                type="button"
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border cursor-help transition-all ${bgColor} ${textColor}`}
                onClick={() => setShowTooltip((prev) => !prev)}
                aria-expanded={showBreakdownTooltip}
                aria-label={`Score breakdown ${formatScore(score)}`}
            >
                {formatScore(score)}
            </button>

            {/* Tooltip */}
            {showBreakdownTooltip && (
                <div
                    ref={setCardRef}
                    className="fixed z-50 w-[min(20rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] px-3 py-2 bg-gray-900 text-white text-xs rounded-lg shadow-xl"
                    style={{ top: `${top}px`, left: `${left}px` }}
                    role="tooltip"
                >
                    <div className="font-bold mb-1">Score Breakdown</div>
                    <div className="space-y-1">
                        {tooltipLines.map((line, idx) => (
                            <div key={`${line}-${idx}`} className="text-gray-300 break-words">
                                {line}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

export default ScoreIndicator;

