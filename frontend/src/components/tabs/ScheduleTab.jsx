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

const normalizeToken = (value) => String(value ?? '').trim().toLowerCase();

const toFiniteNumber = (value, fallback = 0) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const trimTrailingPunctuation = (value) => String(value ?? '').trim().replace(/[.,;:!?]+$/, '');

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

const buildWorkerLookup = (assignments, workers) => {
    const idToName = new Map();
    const nameToId = new Map();

    const register = (workerId, workerName) => {
        const idKey = normalizeToken(workerId);
        const nameKey = normalizeToken(workerName);

        if (idKey && nameKey) {
            if (!idToName.has(idKey)) {
                idToName.set(idKey, nameKey);
            }
            if (!nameToId.has(nameKey)) {
                nameToId.set(nameKey, idKey);
            }
        }
    };

    workers.forEach((worker) => register(worker?.worker_id, worker?.name));
    assignments.forEach((assign) => register(assign?.worker_id, assign?.worker_name));

    return { idToName, nameToId };
};

const resolveWorkerTokens = (workerToken, workerLookup) => {
    const normalized = normalizeToken(workerToken);
    if (!normalized) {
        return new Set();
    }

    const tokens = new Set([normalized]);

    const mappedName = workerLookup.idToName.get(normalized);
    if (mappedName) {
        tokens.add(mappedName);
    }

    const mappedId = workerLookup.nameToId.get(normalized);
    if (mappedId) {
        tokens.add(mappedId);
    }

    return tokens;
};

const extractViolationHints = (description, metadata = {}) => {
    const text = String(description ?? '').trim();
    const safeMetadata = metadata && typeof metadata === 'object' ? metadata : {};

    const metadataWorkerTokens = [];
    if (Array.isArray(safeMetadata.worker_ids)) {
        metadataWorkerTokens.push(...safeMetadata.worker_ids);
    }
    if (Array.isArray(safeMetadata.worker_names)) {
        metadataWorkerTokens.push(...safeMetadata.worker_names);
    }
    ['primary_worker_id', 'primary_worker_name', 'paired_worker_id', 'paired_worker_name'].forEach((key) => {
        if (safeMetadata[key]) {
            metadataWorkerTokens.push(safeMetadata[key]);
        }
    });

    const metadataShiftIdHints = [];
    if (safeMetadata.shift_id) {
        metadataShiftIdHints.push(normalizeToken(safeMetadata.shift_id));
    }

    const metadataShiftNameHint = safeMetadata.shift_name
        ? trimTrailingPunctuation(safeMetadata.shift_name)
        : '';

    const unwantedShiftMatch = text.match(/Worker\s+(.+?)\s+assigned to unwanted shift\s+(.+)$/i);
    if (unwantedShiftMatch) {
        return {
            workerToken: trimTrailingPunctuation(unwantedShiftMatch[1]),
            workerTokens: metadataWorkerTokens,
            shiftNameHint: trimTrailingPunctuation(unwantedShiftMatch[2]),
            shiftIdHints: metadataShiftIdHints,
        };
    }

    const restMatch = text.match(/Worker\s+(.+?)\s+has insufficient rest/i);
    const workerFromRest = restMatch ? trimTrailingPunctuation(restMatch[1]) : '';

    const hoursMatch = text.match(/Worker\s+(.+?)\s+exceeded limit/i);
    const workerFromHours = hoursMatch ? trimTrailingPunctuation(hoursMatch[1]) : '';

    const shiftPairMatch = text.match(/between shifts\s+([^\s]+)\s+and\s+([^\s.]+)\.?/i);
    const shiftIdHints = shiftPairMatch
        ? [trimTrailingPunctuation(shiftPairMatch[1]), trimTrailingPunctuation(shiftPairMatch[2])]
              .map(normalizeToken)
              .filter(Boolean)
        : [];

    const pairShiftMatch = text.match(/in shift\s+(.+?)\.?$/i);
    const shiftNameHintFromText = pairShiftMatch
        ? trimTrailingPunctuation(pairShiftMatch[1])
        : '';

    const pairWorkersTogetherMatch = text.match(
        /Worker\s+(.+?)\s+and\s+Worker\s+(.+?)\s+were assigned together in shift\s+(.+?)\.?$/i
    );
    if (pairWorkersTogetherMatch) {
        return {
            workerToken: '',
            workerTokens: [
                ...metadataWorkerTokens,
                trimTrailingPunctuation(pairWorkersTogetherMatch[1]),
                trimTrailingPunctuation(pairWorkersTogetherMatch[2]),
            ],
            shiftNameHint: trimTrailingPunctuation(pairWorkersTogetherMatch[3]) || metadataShiftNameHint,
            shiftIdHints: metadataShiftIdHints,
        };
    }

    const pairMissingMatch = text.match(
        /Worker\s+(.+?)\s+worked without required pair Worker\s+(.+?)\s+in shift\s+(.+?)\.?$/i
    );
    if (pairMissingMatch) {
        return {
            workerToken: trimTrailingPunctuation(pairMissingMatch[1]),
            workerTokens: [
                ...metadataWorkerTokens,
                trimTrailingPunctuation(pairMissingMatch[1]),
                trimTrailingPunctuation(pairMissingMatch[2]),
            ],
            shiftNameHint: trimTrailingPunctuation(pairMissingMatch[3]) || metadataShiftNameHint,
            shiftIdHints: metadataShiftIdHints,
        };
    }

    return {
        workerToken: workerFromRest || workerFromHours,
        workerTokens: metadataWorkerTokens,
        shiftNameHint: metadataShiftNameHint || shiftNameHintFromText,
        shiftIdHints: [...metadataShiftIdHints, ...shiftIdHints].filter(Boolean),
    };
};

/**
 * Client-side violation injection.
 *
 * Enriches assignments with global_violations by parsing penaltyBreakdown metadata.
 * This bridges the gap between global penalties and per-card visualization.
 */
export const mergeGlobalViolations = (assignments = [], penaltyBreakdown = {}, workers = []) => {
    const clonedAssignments = assignments.map((assign) => ({
        ...assign,
        global_violations: [],
        global_penalty_total: 0,
    }));

    if (!penaltyBreakdown || Object.keys(penaltyBreakdown).length === 0) {
        return clonedAssignments;
    }

    const workerLookup = buildWorkerLookup(clonedAssignments, workers);

    const findAssignmentIndexes = ({ workerTokens, shiftIdHints, shiftNameHint }) => {
        const normalizedShiftNameHint = normalizeToken(shiftNameHint);

        const directMatches = [];

        clonedAssignments.forEach((assign, idx) => {
            const assignWorkerId = normalizeToken(assign.worker_id);
            const assignWorkerName = normalizeToken(assign.worker_name);
            const assignShiftId = normalizeToken(assign.shift_id);
            const assignShiftName = normalizeToken(assign.shift_name);

            const workerMatch = workerTokens.size === 0
                ? true
                : workerTokens.has(assignWorkerId) || workerTokens.has(assignWorkerName);

            const hasShiftHints = shiftIdHints.length > 0 || Boolean(normalizedShiftNameHint);
            const shiftMatch = !hasShiftHints
                ? true
                : shiftIdHints.includes(assignShiftId) ||
                  (normalizedShiftNameHint && normalizedShiftNameHint === assignShiftName);

            if (workerMatch && shiftMatch) {
                directMatches.push(idx);
            }
        });

        if (directMatches.length > 0) {
            return directMatches;
        }

        if (workerTokens.size > 0) {
            const workerFallback = [];
            clonedAssignments.forEach((assign, idx) => {
                const assignWorkerId = normalizeToken(assign.worker_id);
                const assignWorkerName = normalizeToken(assign.worker_name);
                if (workerTokens.has(assignWorkerId) || workerTokens.has(assignWorkerName)) {
                    workerFallback.push(idx);
                }
            });
            if (workerFallback.length > 0) {
                return workerFallback;
            }
        }

        if (shiftIdHints.length > 0 || normalizedShiftNameHint) {
            const shiftFallback = [];
            clonedAssignments.forEach((assign, idx) => {
                const assignShiftId = normalizeToken(assign.shift_id);
                const assignShiftName = normalizeToken(assign.shift_name);
                if (shiftIdHints.includes(assignShiftId) || (normalizedShiftNameHint && normalizedShiftNameHint === assignShiftName)) {
                    shiftFallback.push(idx);
                }
            });
            if (shiftFallback.length > 0) {
                return shiftFallback;
            }
        }

        return [];
    };

    Object.entries(penaltyBreakdown).forEach(([constraintName, data]) => {
        const violations = Array.isArray(data?.violations) ? data.violations : [];

        violations.forEach((rawViolation) => {
            const violation = typeof rawViolation === 'string'
                ? { description: rawViolation, penalty: data?.total_penalty }
                : (rawViolation || {});

            const description = String(violation.description || '').trim();
            if (!description) {
                return;
            }

            const hints = extractViolationHints(description, violation.metadata);
            const workerTokens = new Set();

            (Array.isArray(hints.workerTokens) ? hints.workerTokens : []).forEach((workerToken) => {
                const resolved = resolveWorkerTokens(workerToken, workerLookup);
                resolved.forEach((token) => workerTokens.add(token));
            });

            resolveWorkerTokens(hints.workerToken, workerLookup).forEach((token) => workerTokens.add(token));

            const hasMatchingHints = workerTokens.size > 0
                || (Array.isArray(hints.shiftIdHints) && hints.shiftIdHints.length > 0)
                || Boolean(hints.shiftNameHint);

            if (!hasMatchingHints) {
                return;
            }

            const targetIndexes = findAssignmentIndexes({
                workerTokens,
                shiftIdHints: hints.shiftIdHints,
                shiftNameHint: hints.shiftNameHint,
            });

            if (targetIndexes.length === 0) {
                return;
            }

            const normalizedViolation = {
                constraint: constraintName,
                description,
                penalty: toFiniteNumber(violation.penalty, toFiniteNumber(data?.total_penalty, 0)),
                observed_value: violation.observed_value,
                limit_value: violation.limit_value,
                metadata: violation.metadata,
            };

            const violationDedupKey = `${constraintName}|${description}|${normalizedViolation.penalty}`;

            targetIndexes.forEach((idx) => {
                const assign = clonedAssignments[idx];
                const alreadyExists = assign.global_violations.some((item) => (
                    `${item.constraint}|${item.description}|${item.penalty}` === violationDedupKey
                ));

                if (!alreadyExists) {
                    assign.global_violations.push(normalizedViolation);
                }
            });
        });
    });

    clonedAssignments.forEach((assign) => {
        assign.global_penalty_total = assign.global_violations.reduce(
            (sum, violation) => sum + toFiniteNumber(violation?.penalty, 0),
            0
        );
    });

    return clonedAssignments;
};

/**
 * ScoreBreakdownPanel Component
 *
 * Displays a breakdown of penalties by constraint type for score explainability.
 */
const ScoreBreakdownPanel = ({ penaltyBreakdown }) => {
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

            <div className="p-4">
                <table className="w-full">
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
                                        <div className="text-xs text-gray-500 mt-0.5 truncate max-w-xs">
                                            e.g., {entry.violations[0].description}
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
const ScheduleTab = ({ assignments = [], objectiveValue, theoreticalMax, penaltyBreakdown, workers = [] }) => {
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

    // Group assignments by day of week, then by shift
    const assignmentsByDay = {};

    // Initialize all days
    DAYS_OF_WEEK.forEach((day) => {
        assignmentsByDay[day] = {};
    });

    // Process each assignment
    mergedAssignments.forEach((assign) => {
        // Extract day using robust parsing
        const timeStr = assign.time || '';
        const dayName = extractDayName(timeStr, assign.day);

        // Ensure day exists in our map (handle 'Unknown' gracefully)
        if (!assignmentsByDay[dayName]) {
            if (!assignmentsByDay.Unknown) {
                assignmentsByDay.Unknown = {};
            }
        }

        const targetDay = assignmentsByDay[dayName] ? dayName : 'Unknown';

        // Group by shift name
        const shiftName = assign.shift_name || 'Unknown Shift';
        if (!assignmentsByDay[targetDay][shiftName]) {
            assignmentsByDay[targetDay][shiftName] = [];
        }

        // Add parsed time range for display
        const enrichedAssign = {
            ...assign,
            parsedTimeRange: extractTimeRange(timeStr),
        };

        assignmentsByDay[targetDay][shiftName].push(enrichedAssign);
    });

    // Calculate stats
    const totalAssignments = mergedAssignments.length;
    const uniqueShifts = new Set(mergedAssignments.map((item) => item.shift_name)).size;
    const uniqueWorkers = new Set(mergedAssignments.map((item) => item.worker_name)).size;

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
            <div className="flex flex-wrap gap-4 items-center justify-between">
                <div>
                    <h2 className="text-2xl font-black text-gray-800 flex items-center gap-2">
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
                        <div className="flex items-center gap-4 bg-gradient-to-r from-indigo-50 to-purple-50 px-5 py-3 rounded-xl border-2 border-indigo-200">
                            <div className="text-right">
                                <div className="text-sm text-gray-600 font-medium flex items-center justify-end gap-1">
                                    Total Score
                                    <HelpPopover hintId="objective_score" />
                                </div>
                                <div className="text-2xl font-black text-indigo-700">
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
                                        <div className={`text-2xl font-black ${
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
                <ScoreBreakdownPanel penaltyBreakdown={penaltyBreakdown} />
            )}

            {/* Week Grid */}
            <WeekGrid assignmentsByDay={assignmentsByDay} onShiftClick={handleShiftClick} />

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

