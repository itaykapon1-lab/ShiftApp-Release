// ========================================
// SHIFT CARD - Individual shift display
// ========================================

import React from 'react';
import { Clock, Users, ChevronRight } from 'lucide-react';
import ScoreIndicator from './ScoreIndicator';
import { getDisplayTaskName } from '../../../utils/displayFormatting';

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
const ShiftCard = ({ shiftName, timeRange, assignments = [], onClick, workers = [] }) => {
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
            <div className="bg-gradient-to-r from-indigo-500 to-purple-500 px-2 py-1.5 sm:px-4 sm:py-2 text-white">
                <div className="flex items-start justify-between gap-2">
                    <h4 className="font-bold text-xs sm:text-sm truncate flex-1" title={shiftName}>
                        {shiftName}
                    </h4>
                    <ChevronRight className="hidden w-4 h-4 opacity-70 sm:block" />
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-1 sm:gap-2 text-[10px] sm:text-xs text-indigo-100">
                    <Clock className="w-3 h-3" />
                    <span>{timeRange}</span>
                    <span className="mx-1">|</span>
                    <Users className="w-3 h-3" />
                    <span>{assignments.length} assigned</span>
                </div>
            </div>

            {/* Assignments */}
            <div className="p-1.5 sm:p-3 space-y-2 sm:space-y-3">
                {Object.entries(taskGroups).map(([taskName, taskAssignments], taskIdx) => (
                    <div key={taskName} className="space-y-1">
                        {/* Task name header (only if multiple tasks or non-default) */}
                        {(Object.keys(taskGroups).length > 1 || taskName !== 'General') && (
                            <div className="text-xs font-bold text-gray-500 uppercase tracking-wide">
                                {getDisplayTaskName(taskName, taskIdx)}
                            </div>
                        )}

                        {/* Workers in this task */}
                        {taskAssignments.map((assign, idx) => (
                            <div
                                key={`${assign.worker_name}-${idx}`}
                                className="flex flex-col gap-2 py-1.5 px-2 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors sm:flex-row sm:items-center sm:justify-between"
                            >
                                <div className="flex min-w-0 items-center gap-2">
                                    <div className="w-6 h-6 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold text-xs flex-shrink-0">
                                        {assign.worker_name?.charAt(0) || '?'}
                                    </div>
                                    <span className="text-xs sm:text-sm font-medium text-gray-800 truncate">
                                        {assign.worker_name}
                                    </span>
                                </div>
                                <div className="self-start sm:self-center">
                                    <ScoreIndicator
                                        score={assign.score || 0}
                                        breakdown={assign.score_breakdown}
                                        globalViolations={assign.global_violations}
                                        employees={workers}
                                    />
                                </div>
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

