// ========================================
// SCHEDULE TAB - Visual week grid display
// ========================================

import React, { useMemo, useState } from 'react';
import { Calendar, Info, AlertTriangle, TrendingDown, TrendingUp } from 'lucide-react';
import WeekGrid from './schedule/WeekGrid';
import ShiftDetailsModal from '../modals/ShiftDetailsModal';
import { HelpButton, HelpPopover } from '../../help';
import {
    EFFICIENCY_THRESHOLD_GOOD,
    EFFICIENCY_THRESHOLD_WARNING,
} from '../../utils/constants';
import { formatDiagnosticMessage } from '../../utils/displayFormatting';
import { mergeGlobalViolations } from './schedule/mergeGlobalViolations';

const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

// Map day abbreviations to full names (for parsing "Mon 08:00 - 16:00" format)
const DAY_ABBREV_MAP = {
    Sun: 'Sunday',
    Mon: 'Monday',
    Tue: 'Tuesday',
    Wed: 'Wednesday',
    Thu: 'Thursday',
    Fri: 'Friday',
    Sat: 'Saturday',
};

/**
 * Extracts day name from various time string formats:
 * - "Mon 08:00 - 16:00" -> "Monday"
 * - "2026-01-05T08:00:00" -> "Monday" (via date parsing)
 * - Or falls back to assign.day if available
 */
const extractDayName = (timeStr, assignDay) => {
    if (!timeStr) {
        return assignDay || 'Unknown';
    }

    // Format 1: ISO timestamp "2026-01-05T08:00:00"
    if (timeStr.includes('T')) {
        const dateStr = timeStr.split('T')[0];
        const date = new Date(`${dateStr}T00:00:00`);
        if (!Number.isNaN(date.getTime())) {
            return DAYS_OF_WEEK[date.getDay()];
        }
    }

    // Format 2: Day abbreviation "Mon 08:00 - 16:00"
    const abbrevMatch = timeStr.match(/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\b/i);
    if (abbrevMatch) {
        const abbrev = abbrevMatch[1].charAt(0).toUpperCase() + abbrevMatch[1].slice(1, 3).toLowerCase();
        return DAY_ABBREV_MAP[abbrev] || 'Unknown';
    }

    // Fallback to assign.day or Unknown
    return assignDay || 'Unknown';
};

/**
 * Extracts time range from various formats:
 * - "Mon 08:00 - 16:00" -> "08:00 - 16:00"
 * - "2026-01-05T08:00:00" -> "08:00"
 */
const extractTimeRange = (timeStr) => {
    if (!timeStr) return '';

    // Format 1: ISO timestamp
    if (timeStr.includes('T')) {
        return timeStr.split('T')[1]?.slice(0, 5) || '';
    }

    // Format 2: "Mon 08:00 - 16:00" -> "08:00 - 16:00"
    const timeMatch = timeStr.match(/(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})/);
    if (timeMatch) {
        return `${timeMatch[1]} - ${timeMatch[2]}`;
    }

    return timeStr;
};

/**
 * ScoreBreakdownPanel Component
 *
 * Displays a breakdown of penalties by constraint type for score explainability.
 */
const ScoreBreakdownPanel = ({ penaltyBreakdown, workers = EMPTY_WORKERS }) => {
    if (!penaltyBreakdown || Object.keys(penaltyBreakdown).length === 0) {
        return null;
    }

    // Convert breakdown object to sorted array
    const breakdownEntries = Object.entries(penaltyBreakdown)
        .map(([constraintName, data]) => ({
            name: constraintName,
            totalPenalty: data.total_penalty || 0,
            violationCount: data.violation_count || 0,
            violations: data.violations || [],
        }))
        .sort((a, b) => a.totalPenalty - b.totalPenalty); // Most negative first

    const totalPenalty = breakdownEntries.reduce((sum, entry) => sum + entry.totalPenalty, 0);

    return (
        <div className="bg-white rounded-xl border-2 border-gray-200 shadow-lg overflow-hidden">
            <div className="bg-gradient-to-r from-amber-50 to-orange-50 px-5 py-3 border-b border-gray-200">
                <h3 className="font-bold text-gray-800 flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5 text-amber-600" />
                    Score Breakdown (Explainability)
                </h3>
                <p className="text-sm text-gray-600 mt-1">
                    Penalties applied to the optimal score
                </p>
            </div>

            <div className="p-4 overflow-x-auto">
                <table className="w-full min-w-[480px]">
                    <thead>
                        <tr className="text-left text-sm text-gray-500 border-b">
                            <th className="pb-2 font-semibold">Constraint</th>
                            <th className="pb-2 font-semibold text-center">Violations</th>
                            <th className="pb-2 font-semibold text-right">Penalty Impact</th>
                        </tr>
                    </thead>
                    <tbody>
                        {breakdownEntries.map((entry, idx) => (
                            <tr
                                key={entry.name}
                                className={`border-b border-gray-100 ${idx % 2 === 0 ? 'bg-gray-50' : 'bg-white'}`}
                            >
                                <td className="py-3 pr-4">
                                    <div className="font-medium text-gray-800">
                                        {entry.name.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())}
                                    </div>
                                    {entry.violations.length > 0 && entry.violations[0]?.description && (
                                        <div className="text-xs text-gray-500 mt-0.5 truncate max-w-[150px] sm:max-w-xs">
                                            e.g., {formatDiagnosticMessage(entry.violations[0].description, workers)}
                                        </div>
                                    )}
                                </td>
                                <td className="py-3 text-center">
                                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-sm font-medium ${
                                        entry.violationCount > 0
                                            ? 'bg-red-100 text-red-800'
                                            : 'bg-green-100 text-green-800'
                                    }`}>
                                        {entry.violationCount} {entry.violationCount === 1 ? 'instance' : 'instances'}
                                    </span>
                                </td>
                                <td className="py-3 text-right">
                                    <div className={`flex items-center justify-end gap-1 font-bold ${
                                        entry.totalPenalty < 0
                                            ? 'text-red-600'
                                            : entry.totalPenalty > 0
                                                ? 'text-green-600'
                                                : 'text-gray-600'
                                    }`}>
                                        {entry.totalPenalty < 0 ? (
                                            <TrendingDown className="w-4 h-4" />
                                        ) : entry.totalPenalty > 0 ? (
                                            <TrendingUp className="w-4 h-4" />
                                        ) : null}
                                        {entry.totalPenalty > 0 ? '+' : ''}{entry.totalPenalty.toFixed(1)} pts
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                    <tfoot>
                        <tr className="bg-gray-100 font-bold">
                            <td className="py-3 pr-4 text-gray-800">Total Penalty</td>
                            <td className="py-3 text-center text-gray-600">
                                {breakdownEntries.reduce((sum, entry) => sum + entry.violationCount, 0)} total
                            </td>
                            <td className={`py-3 text-right ${
                                totalPenalty < 0 ? 'text-red-700' : totalPenalty > 0 ? 'text-green-700' : 'text-gray-700'
                            }`}>
                                {totalPenalty > 0 ? '+' : ''}{totalPenalty.toFixed(1)} pts
                            </td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        </div>
    );
};

/**
 * ScheduleTab Component
 *
 * Main container for the visual schedule display.
 * Groups assignments by day of week and renders a WeekGrid.
 *
 * Props:
 * - assignments: Array - solver assignments
 *   Each: { worker_name, shift_name, time, task, score, score_breakdown }
 * - objectiveValue: Number - total score achieved
 * - theoreticalMax: Number - maximum possible score
 * - penaltyBreakdown: Object - penalty breakdown by constraint type
 * - workers: Array - all workers (for detailed view in modal)
 */
const EMPTY_ASSIGNMENTS = [];
const EMPTY_WORKERS = [];

const ScheduleTab = ({ assignments = EMPTY_ASSIGNMENTS, objectiveValue, theoreticalMax, penaltyBreakdown, workers = EMPTY_WORKERS }) => {
    // Modal state for shift details
    const [selectedShift, setSelectedShift] = useState(null);
    const [isModalOpen, setIsModalOpen] = useState(false);

    const handleShiftClick = (shiftData) => {
        setSelectedShift(shiftData);
        setIsModalOpen(true);
    };

    const handleCloseModal = () => {
        setIsModalOpen(false);
        setSelectedShift(null);
    };

    const mergedAssignments = useMemo(
        () => mergeGlobalViolations(assignments, penaltyBreakdown || {}, workers),
        [assignments, penaltyBreakdown, workers]
    );

    // Group assignments in two passes:
    // 1) identity grouping by shift_id (or day+name+time fallback when legacy data lacks shift_id)
    // 2) per-day display-name disambiguation for duplicate names only
    const { assignmentsByDay, totalAssignments, uniqueShifts, uniqueWorkers } = useMemo(() => {
        const byDay = {};
        const shiftKeys = new Set();

        DAYS_OF_WEEK.forEach((day) => {
            byDay[day] = {};
        });
        byDay.Unknown = {};

        mergedAssignments.forEach((assign) => {
            const timeStr = assign.time || '';
            const dayName = extractDayName(timeStr, assign.day);
            const timeRange = extractTimeRange(timeStr);
            const baseName = assign.shift_name || 'Unknown Shift';

            const targetDay = byDay[dayName] ? dayName : 'Unknown';
            const fallbackKey = `${targetDay}::${baseName}::${timeRange}`;
            const shiftKey = assign.shift_id || fallbackKey;
            if (!byDay[targetDay][shiftKey]) {
                byDay[targetDay][shiftKey] = {
                    shiftKey,
                    shiftId: assign.shift_id || null,
                    baseName,
                    displayName: baseName,
                    timeRange,
                    assignments: [],
                };
            }

            const enrichedAssign = {
                ...assign,
                parsedTimeRange: timeRange,
            };

            byDay[targetDay][shiftKey].assignments.push(enrichedAssign);
            shiftKeys.add(shiftKey);
        });

        Object.keys(byDay).forEach((day) => {
            const groups = Object.values(byDay[day]);
            const nameCounts = {};

            groups.forEach((group) => {
                nameCounts[group.baseName] = (nameCounts[group.baseName] || 0) + 1;
            });

            groups.forEach((group) => {
                group.displayName = nameCounts[group.baseName] > 1 && group.timeRange
                    ? `${group.baseName} (${group.timeRange})`
                    : group.baseName;
            });
        });

        return {
            assignmentsByDay: byDay,
            totalAssignments: mergedAssignments.length,
            uniqueShifts: shiftKeys.size,
            uniqueWorkers: new Set(mergedAssignments.map((item) => item.worker_name)).size,
        };
    }, [mergedAssignments]);

    // Calculate efficiency percentage
    const efficiency = (theoreticalMax && objectiveValue !== undefined)
        ? ((objectiveValue / theoreticalMax) * 100).toFixed(1)
        : null;

    // Empty state
    if (mergedAssignments.length === 0) {
        return (
            <div className="space-y-6">
                <div className="flex justify-end">
                    <HelpButton topicId="schedule.interpretation" label="Help" />
                </div>
                <div className="text-center py-16">
                    <Calendar className="w-16 h-16 mx-auto text-gray-300 mb-4" />
                    <h3 className="text-xl font-bold text-gray-500 mb-2">No Schedule Available</h3>
                    <p className="text-gray-400 max-w-md mx-auto">
                        Run the solver to generate a schedule. The visual week grid will appear here
                        showing all worker assignments organized by day.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header Stats */}
            <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:gap-4 sm:items-center sm:justify-between">
                <div>
                    <h2 className="text-xl sm:text-2xl font-black text-gray-800 flex items-center gap-2">
                        <Calendar className="w-7 h-7 text-indigo-600" />
                        Weekly Schedule
                    </h2>
                    <p className="text-sm text-gray-500 mt-1">
                        {totalAssignments} assignments across {uniqueShifts} shifts with {uniqueWorkers} workers
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    <HelpButton topicId="schedule.interpretation" label="Help" />
                    {/* Score Summary */}
                    {objectiveValue !== undefined && (
                        <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 bg-gradient-to-r from-indigo-50 to-purple-50 px-3 py-2 sm:px-5 sm:py-3 rounded-xl border-2 border-indigo-200">
                            <div className="text-right">
                                <div className="text-sm text-gray-600 font-medium flex items-center justify-end gap-1">
                                    Total Score
                                    <HelpPopover hintId="objective_score" />
                                </div>
                                <div className="text-lg sm:text-2xl font-black text-indigo-700">
                                    {objectiveValue?.toFixed(1) || '0.0'}
                                </div>
                            </div>
                            {efficiency && (
                                <>
                                    <div className="w-px h-10 bg-indigo-200" />
                                    <div className="text-right">
                                        <div className="text-sm text-gray-600 font-medium flex items-center justify-end gap-1">
                                            Efficiency
                                            <HelpPopover hintId="efficiency_ratio" placement="left" />
                                        </div>
                                        <div className={`text-lg sm:text-2xl font-black ${
                                            parseFloat(efficiency) >= EFFICIENCY_THRESHOLD_GOOD ? 'text-green-600' :
                                                parseFloat(efficiency) >= EFFICIENCY_THRESHOLD_WARNING ? 'text-yellow-600' : 'text-red-600'
                                        }`}>
                                            {efficiency}%
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Info Banner */}
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-start gap-3">
                <Info className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-blue-800">
                    <strong>Tip:</strong> Click on any shift card to see detailed information
                    about assigned workers, their skills, and preference matches.
                    Green scores indicate preference matches, red indicates penalties.
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-700 border border-green-300">Green</span>
                        <span className="text-xs">positive and no global violation</span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700 border border-red-300">Red</span>
                        <span className="text-xs">negative or mapped global violation</span>
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-700 border border-gray-300">Gray</span>
                        <span className="text-xs">neutral</span>
                        <HelpPopover hintId="global_violation_mapping" placement="bottom" />
                    </div>
                </div>
            </div>

            {/* Score Breakdown Panel (Explainability) */}
            {penaltyBreakdown && Object.keys(penaltyBreakdown).length > 0 && (
                <ScoreBreakdownPanel penaltyBreakdown={penaltyBreakdown} workers={workers} />
            )}

            {/* Week Grid */}
            <WeekGrid assignmentsByDay={assignmentsByDay} onShiftClick={handleShiftClick} workers={workers} />

            {/* Shift Details Modal */}
            <ShiftDetailsModal
                isOpen={isModalOpen}
                onClose={handleCloseModal}
                shift={selectedShift}
                workers={workers}
            />
        </div>
    );
};

export default ScheduleTab;
