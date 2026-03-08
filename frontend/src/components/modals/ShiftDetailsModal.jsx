// ========================================
// SHIFT DETAILS MODAL - Expanded View
// ========================================

import React from 'react';
import { X, Clock, Users, Briefcase, CheckCircle, XCircle, Star, AlertTriangle } from 'lucide-react';

// ---------------------------------------------------------------------------
// Time helpers for overlap-based preference matching
// ---------------------------------------------------------------------------

/**
 * Parses a "HH:MM" string to total minutes since midnight.
 * Returns NaN if the string is malformed.
 */
const parseTimeToMinutes = (timeStr) => {
    if (!timeStr || typeof timeStr !== 'string') return NaN;
    const parts = timeStr.trim().split(':');
    if (parts.length < 2) return NaN;
    const h = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    if (Number.isNaN(h) || Number.isNaN(m)) return NaN;
    return h * 60 + m;
};

/**
 * Finds the availability entry (if any) that contains or overlaps the shift's
 * time window on the matching day.
 *
 * @param {string} assignTime  - e.g. "Mon 08:00 - 16:00"
 * @param {object} workerAvailability - e.g. { MON: { timeRange: "07:00-17:00", preference: "HIGH" } }
 * @returns {{ dayKey: string, entry: object|string }|null}
 */
const findMatchingAvailability = (assignTime, workerAvailability) => {
    if (!assignTime || !workerAvailability || typeof workerAvailability !== 'object') return null;

    // Extract 3-letter day prefix: "Mon 08:00 - 16:00" → "MON"
    const dayMatch = assignTime.match(/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\b/i);
    if (!dayMatch) return null;
    const dayKey = dayMatch[1].toUpperCase();

    const dayAvail = workerAvailability[dayKey];
    if (!dayAvail) return null;

    const availTimeRange = typeof dayAvail === 'string' ? dayAvail : (dayAvail?.timeRange || '');
    if (!availTimeRange) return null;

    // Extract shift time window from "Mon 08:00 - 16:00"
    const shiftTimeMatch = assignTime.match(/(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})/);
    if (!shiftTimeMatch) return null;
    const shiftStart = parseTimeToMinutes(shiftTimeMatch[1]);
    const shiftEnd   = parseTimeToMinutes(shiftTimeMatch[2]);
    if (Number.isNaN(shiftStart) || Number.isNaN(shiftEnd)) return null;

    // Extract availability time window
    const availTimeMatch = availTimeRange.match(/(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})/);
    if (!availTimeMatch) return null;
    const availStart = parseTimeToMinutes(availTimeMatch[1]);
    let   availEnd   = parseTimeToMinutes(availTimeMatch[2]);
    if (Number.isNaN(availStart) || Number.isNaN(availEnd)) return null;

    // Handle overnight availability windows (e.g. "22:00-06:00" → availEnd wraps to +24h)
    if (availEnd <= availStart) availEnd += 24 * 60;

    // 1. Containment check — shift fully inside availability window
    if (availStart <= shiftStart && shiftEnd <= availEnd) return { dayKey, entry: dayAvail };

    // 2. Overlap fallback — partial overlap counts too
    if (availStart < shiftEnd && shiftStart < availEnd) return { dayKey, entry: dayAvail };

    return null;
};

/**
 * ShiftDetailsModal Component
 *
 * Displays detailed information about a shift and its assignments.
 *
 * Props:
 * - isOpen: Boolean - whether the modal is visible
 * - onClose: Function - callback to close the modal
 * - shift: Object - shift data with name, timeRange, assignments
 * - workers: Array - all workers (for looking up details)
 */
const ShiftDetailsModal = ({ isOpen, onClose, shift, workers = [] }) => {
    if (!isOpen || !shift) return null;

    const { shiftName, timeRange, assignments = [] } = shift;

    // Create a worker lookup map
    const workerMap = {};
    workers.forEach(w => {
        workerMap[w.name] = w;
        workerMap[w.worker_id] = w;
    });

    // Group assignments by task
    const taskGroups = {};
    assignments.forEach(assign => {
        const task = assign.task || 'General';
        if (!taskGroups[task]) {
            taskGroups[task] = [];
        }
        taskGroups[task].push(assign);
    });

    // Extract required skills from role_details
    const parseRoleSkills = (roleDetails) => {
        if (!roleDetails) return [];
        // Format: "Skills: ['Chef', 'Sous Chef']" or similar
        const match = roleDetails.match(/\[(.*?)\]/);
        if (match) {
            return match[1].split(',').map(s => s.trim().replace(/['"]/g, '')).filter(Boolean);
        }
        return [];
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                onClick={onClose}
            />

            {/* Modal */}
            <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-hidden mx-4">
                {/* Header */}
                <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-4 text-white">
                    <div className="flex justify-between items-start">
                        <div>
                            <h2 className="text-2xl font-black">{shiftName}</h2>
                            <div className="flex items-center gap-3 mt-1 text-indigo-100">
                                <Clock className="w-4 h-4" />
                                <span className="font-medium">{timeRange}</span>
                                <span className="mx-2">|</span>
                                <Users className="w-4 h-4" />
                                <span className="font-medium">{assignments.length} workers assigned</span>
                            </div>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-white/20 rounded-full transition-colors"
                        >
                            <X className="w-6 h-6" />
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div className="p-6 overflow-y-auto max-h-[calc(90vh-120px)]">
                    {/* Tasks & Requirements Overview */}
                    <div className="mb-6">
                        <h3 className="text-lg font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <Briefcase className="w-5 h-5 text-indigo-600" />
                            Tasks & Requirements
                        </h3>
                        <div className="grid gap-3">
                            {Object.entries(taskGroups).map(([taskName, taskAssignments]) => {
                                // Collect unique skills required for this task
                                const requiredSkills = new Set();
                                taskAssignments.forEach(a => {
                                    parseRoleSkills(a.role_details).forEach(s => requiredSkills.add(s));
                                });

                                return (
                                    <div
                                        key={taskName}
                                        className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-4 border-2 border-indigo-200"
                                    >
                                        <div className="flex justify-between items-center mb-2">
                                            <h4 className="font-bold text-indigo-900">{taskName}</h4>
                                            <span className="px-3 py-1 bg-indigo-600 text-white rounded-full text-sm font-bold">
                                                {taskAssignments.length} assigned
                                            </span>
                                        </div>
                                        {requiredSkills.size > 0 && (
                                            <div className="flex flex-wrap gap-2">
                                                {[...requiredSkills].map(skill => (
                                                    <span
                                                        key={skill}
                                                        className="px-2 py-1 bg-white border border-indigo-300 rounded-lg text-xs font-medium text-indigo-700"
                                                    >
                                                        {skill}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {/* Assigned Workers - Deep Dive */}
                    <div>
                        <h3 className="text-lg font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <Users className="w-5 h-5 text-green-600" />
                            Assigned Workers
                        </h3>
                        <div className="space-y-4">
                            {assignments.map((assign, idx) => {
                                const workerData = workerMap[assign.worker_name] || workerMap[assign.worker_id];
                                const workerSkills = workerData?.attributes?.skills || {};
                                const workerAvailability = workerData?.attributes?.availability || {};
                                const requiredSkills = parseRoleSkills(assign.role_details);
                                const score = assign.score || 0;
                                const isPositiveScore = score > 0;
                                const isNegativeScore = score < 0;

                                // Determine preference match using overlap-based availability check.
                                // assign.time is expected to be e.g. "Mon 08:00 - 16:00".
                                const availMatch    = findMatchingAvailability(assign.time, workerAvailability);
                                const matchedDayKey = availMatch?.dayKey ?? null;
                                const matchedEntry  = availMatch?.entry ?? null;
                                const availPref     = matchedEntry
                                    ? (typeof matchedEntry === 'object'
                                        ? (matchedEntry.preference || 'NEUTRAL')
                                        : 'NEUTRAL')
                                    : null;

                                // Prefer the explicit availability preference; fall back to score sign.
                                const preferenceStatus =
                                    availPref === 'HIGH'    ? 'PREFERRED' :
                                    availPref === 'LOW'     ? 'AVOIDED'   :
                                    availPref === 'NEUTRAL' ? 'NEUTRAL'   :
                                    isPositiveScore         ? 'PREFERRED' :
                                    isNegativeScore         ? 'AVOIDED'   : 'NEUTRAL';

                                return (
                                    <div
                                        key={`${assign.worker_name}-${idx}`}
                                        className="bg-white rounded-xl border-2 border-gray-200 shadow-md overflow-hidden hover:shadow-lg transition-shadow"
                                    >
                                        {/* Worker Header */}
                                        <div className={`px-4 py-3 flex justify-between items-center ${
                                            isPositiveScore ? 'bg-green-50 border-b-2 border-green-200' :
                                            isNegativeScore ? 'bg-red-50 border-b-2 border-red-200' :
                                            'bg-gray-50 border-b-2 border-gray-200'
                                        }`}>
                                            <div className="flex items-center gap-3">
                                                <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-white ${
                                                    isPositiveScore ? 'bg-green-500' :
                                                    isNegativeScore ? 'bg-red-500' :
                                                    'bg-gray-500'
                                                }`}>
                                                    {assign.worker_name?.charAt(0) || '?'}
                                                </div>
                                                <div>
                                                    <h4 className="font-bold text-gray-900">{assign.worker_name}</h4>
                                                    <p className="text-sm text-gray-600">{assign.task || 'General Task'}</p>
                                                </div>
                                            </div>
                                            <div className="text-right">
                                                <div className={`flex items-center gap-1 px-3 py-1 rounded-full font-bold ${
                                                    isPositiveScore ? 'bg-green-100 text-green-700' :
                                                    isNegativeScore ? 'bg-red-100 text-red-700' :
                                                    'bg-gray-100 text-gray-600'
                                                }`}>
                                                    {isPositiveScore ? <Star className="w-4 h-4" /> :
                                                     isNegativeScore ? <AlertTriangle className="w-4 h-4" /> :
                                                     null}
                                                    <span>{score > 0 ? `+${score}` : score}</span>
                                                </div>
                                                <p className="text-xs text-gray-500 mt-1">
                                                    {assign.score_breakdown || '-'}
                                                </p>
                                            </div>
                                        </div>

                                        {/* Worker Details */}
                                        <div className="p-4 grid md:grid-cols-2 gap-4">
                                            {/* Skills Match */}
                                            <div>
                                                <h5 className="text-sm font-bold text-gray-700 mb-2">Skills</h5>
                                                <div className="flex flex-wrap gap-2">
                                                    {Object.entries(workerSkills).map(([skill, level]) => {
                                                        const isRequired = requiredSkills.includes(skill);
                                                        return (
                                                            <span
                                                                key={skill}
                                                                className={`px-2 py-1 rounded-lg text-xs font-medium flex items-center gap-1 ${
                                                                    isRequired
                                                                        ? 'bg-green-100 border border-green-400 text-green-800'
                                                                        : 'bg-gray-100 border border-gray-300 text-gray-700'
                                                                }`}
                                                            >
                                                                {isRequired && <CheckCircle className="w-3 h-3" />}
                                                                {skill} <span className="font-bold">(Lvl {level})</span>
                                                            </span>
                                                        );
                                                    })}
                                                    {Object.keys(workerSkills).length === 0 && (
                                                        <span className="text-sm text-gray-400 italic">No skills listed</span>
                                                    )}
                                                </div>
                                            </div>

                                            {/* Availability */}
                                            <div>
                                                <h5 className="text-sm font-bold text-gray-700 mb-2">Availability</h5>
                                                <div className="flex flex-wrap gap-2">
                                                    {Object.entries(workerAvailability).map(([day, data]) => {
                                                        const timeR = typeof data === 'string' ? data :
                                                            data?.timeRange || '?';
                                                        const pref = typeof data === 'object' ? data?.preference : 'NEUTRAL';
                                                        const isActive = day === matchedDayKey;

                                                        return (
                                                            <span
                                                                key={day}
                                                                className={`px-2 py-1 rounded-lg text-xs font-medium transition-all ${
                                                                    isActive
                                                                        ? 'ring-2 ring-offset-1 ring-indigo-500 font-bold ' + (
                                                                            pref === 'HIGH' ? 'bg-green-100 border border-green-400 text-green-800' :
                                                                            pref === 'LOW'  ? 'bg-red-100 border border-red-400 text-red-800' :
                                                                                             'bg-blue-100 border border-blue-300 text-blue-800'
                                                                          )
                                                                        : 'opacity-60 ' + (
                                                                            pref === 'HIGH' ? 'bg-green-100 border border-green-400 text-green-800' :
                                                                            pref === 'LOW'  ? 'bg-red-100 border border-red-400 text-red-800' :
                                                                                             'bg-blue-100 border border-blue-300 text-blue-800'
                                                                          )
                                                                }`}
                                                                title={isActive ? `This window covers the shift` : undefined}
                                                            >
                                                                {isActive && <span className="mr-1">↑</span>}
                                                                <span className="font-bold">{day}</span>: {timeR}
                                                            </span>
                                                        );
                                                    })}
                                                    {Object.keys(workerAvailability).length === 0 && (
                                                        <span className="text-sm text-gray-400 italic">No availability set</span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>

                                        {/* Preference Match Indicator */}
                                        <div className={`px-4 py-2 text-sm font-medium ${
                                            preferenceStatus === 'PREFERRED' ? 'bg-green-50 text-green-700' :
                                            preferenceStatus === 'AVOIDED' ? 'bg-red-50 text-red-700' :
                                            'bg-gray-50 text-gray-600'
                                        }`}>
                                            {preferenceStatus === 'PREFERRED' && (
                                                <span className="flex items-center gap-2">
                                                    <CheckCircle className="w-4 h-4" />
                                                    {matchedDayKey
                                                        ? `Shift falls within worker's ${matchedDayKey} availability window — preference: ${availPref}`
                                                        : "This assignment matches the worker's preference"}
                                                </span>
                                            )}
                                            {preferenceStatus === 'AVOIDED' && (
                                                <span className="flex items-center gap-2">
                                                    <XCircle className="w-4 h-4" />
                                                    {matchedDayKey
                                                        ? `Shift falls within worker's ${matchedDayKey} availability window — preference: ${availPref}`
                                                        : "This worker preferred to avoid this time slot"}
                                                </span>
                                            )}
                                            {preferenceStatus === 'NEUTRAL' && (
                                                <span className="flex items-center gap-2">
                                                    {matchedDayKey
                                                        ? `Shift falls within worker's ${matchedDayKey} availability window — preference: NEUTRAL`
                                                        : "Neutral preference for this time slot"}
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="border-t-2 border-gray-200 px-6 py-4 bg-gray-50">
                    <button
                        onClick={onClose}
                        className="w-full px-4 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl font-bold hover:from-indigo-700 hover:to-purple-700 transition-colors"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ShiftDetailsModal;
