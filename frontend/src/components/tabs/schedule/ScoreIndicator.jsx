// ========================================
// SCORE INDICATOR - Visual score badges
// ========================================

import React, { useState } from 'react';

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
const ScoreIndicator = ({ score, breakdown, globalViolations = [] }) => {
    const [showTooltip, setShowTooltip] = useState(false);

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
        tooltipLines.push(String(breakdown));
    }

    if (hasGlobalViolations) {
        normalizedGlobalViolations.forEach((description) => {
            tooltipLines.push(`Global: ${description}`);
        });
    }

    const showBreakdownTooltip = showTooltip && tooltipLines.length > 0;

    return (
        <div className="relative inline-block">
            <span
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold border cursor-help transition-all ${bgColor} ${textColor}`}
                onMouseEnter={() => setShowTooltip(true)}
                onMouseLeave={() => setShowTooltip(false)}
            >
                {formatScore(score)}
            </span>

            {/* Tooltip */}
            {showBreakdownTooltip && (
                <div className="absolute z-50 bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg shadow-xl min-w-[220px] max-w-[320px]">
                    <div className="font-bold mb-1">Score Breakdown</div>
                    <div className="space-y-1">
                        {tooltipLines.map((line, idx) => (
                            <div key={`${line}-${idx}`} className="text-gray-300 break-words">
                                {line}
                            </div>
                        ))}
                    </div>
                    {/* Arrow */}
                    <div className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
                </div>
            )}
        </div>
    );
};

export default ScoreIndicator;

