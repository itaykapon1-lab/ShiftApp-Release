// ========================================
// SHIFT CARD - Individual shift display
// ========================================

import React from 'react';
import { Clock, Users, ChevronRight } from 'lucide-react';
import ScoreIndicator from './ScoreIndicator';

/**
 * ShiftCard Component
 *
 * Displays a single shift with its assigned workers.
 * Clicking the card opens a detailed modal view.
 *
 * Props:
 * - shiftName: String - the name of the shift
 * - timeRange: String - formatted time range (e.g., "08:00-16:00")
 * - assignments: Array - list of worker assignments for this shift
 *   - Each assignment: { worker_name, task, score, score_breakdown, role_details, global_violations }
 * - onClick: Function - callback when card is clicked (for opening modal)
 */
const ShiftCard = ({ shiftName, timeRange, assignments = [], onClick }) => {
    // Group assignments by task
    const taskGroups = {};
    assignments.forEach((assign) => {
        const task = assign.task || 'General';
        if (!taskGroups[task]) {
            taskGroups[task] = [];
        }
        taskGroups[task].push(assign);
    });

    return (
        <div
            className="bg-white rounded-xl border-2 border-gray-200 shadow-md overflow-hidden hover:shadow-lg transition-all cursor-pointer hover:border-indigo-400 hover:scale-[1.02]"
            onClick={() => onClick && onClick({ shiftName, timeRange, assignments })}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => event.key === 'Enter' && onClick && onClick({ shiftName, timeRange, assignments })}
        >
            {/* Header */}
            <div className="bg-gradient-to-r from-indigo-500 to-purple-500 px-4 py-2 text-white">
                <div className="flex justify-between items-start">
                    <h4 className="font-bold text-sm truncate flex-1" title={shiftName}>
                        {shiftName}
                    </h4>
                    <ChevronRight className="w-4 h-4 opacity-70" />
                </div>
                <div className="flex items-center gap-2 text-xs text-indigo-100 mt-0.5">
                    <Clock className="w-3 h-3" />
                    <span>{timeRange}</span>
                    <span className="mx-1">|</span>
                    <Users className="w-3 h-3" />
                    <span>{assignments.length} assigned</span>
                </div>
            </div>

            {/* Assignments */}
            <div className="p-3 space-y-3">
                {Object.entries(taskGroups).map(([taskName, workers]) => (
                    <div key={taskName} className="space-y-1">
                        {/* Task name header (only if multiple tasks or non-default) */}
                        {(Object.keys(taskGroups).length > 1 || taskName !== 'General') && (
                            <div className="text-xs font-bold text-gray-500 uppercase tracking-wide">
                                {taskName}
                            </div>
                        )}

                        {/* Workers in this task */}
                        {workers.map((assign, idx) => (
                            <div
                                key={`${assign.worker_name}-${idx}`}
                                className="flex items-center justify-between py-1.5 px-2 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
                            >
                                <div className="flex items-center gap-2 min-w-0">
                                    <div className="w-6 h-6 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold text-xs flex-shrink-0">
                                        {assign.worker_name?.charAt(0) || '?'}
                                    </div>
                                    <span className="text-sm font-medium text-gray-800 truncate">
                                        {assign.worker_name}
                                    </span>
                                </div>
                                <ScoreIndicator
                                    score={assign.score || 0}
                                    breakdown={assign.score_breakdown}
                                    globalViolations={assign.global_violations}
                                />
                            </div>
                        ))}
                    </div>
                ))}

                {/* Empty state */}
                {assignments.length === 0 && (
                    <div className="text-center py-4 text-gray-400 text-sm">
                        No workers assigned
                    </div>
                )}
            </div>
        </div>
    );
};

export default ShiftCard;

