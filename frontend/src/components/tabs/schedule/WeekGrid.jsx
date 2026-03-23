// ========================================
// WEEK GRID - 7-column day grid
// ========================================

import React from 'react';
import ShiftCard from './ShiftCard';

const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

/**
 * WeekGrid Component
 *
 * Displays a 7-column grid with one column per day of the week.
 * Each column contains the shifts scheduled for that day.
 *
 * Props:
 * - assignmentsByDay: Object - pre-grouped shift cards by day
 *   {
 *     'Monday': {
 *       '<shiftKey>': {
 *         shiftKey,
 *         displayName,
 *         timeRange,
 *         assignments: [...]
 *       }
 *     }
 *   }
 * - onShiftClick: Function - callback when a shift card is clicked
 */
const WeekGrid = ({ assignmentsByDay, onShiftClick }) => {
    return (
        <div className="grid grid-cols-7 gap-3 min-h-[500px]">
            {DAYS_OF_WEEK.map((day) => {
                const shiftsForDay = assignmentsByDay[day] || {};
                const shiftGroups = Object.values(shiftsForDay);
                const hasShifts = shiftGroups.length > 0;

                return (
                    <div key={day} className="flex flex-col">
                        {/* Day Header */}
                        <div className={`text-center py-2 rounded-t-xl font-bold text-sm ${
                            hasShifts
                                ? 'bg-indigo-600 text-white'
                                : 'bg-gray-200 text-gray-600'
                        }`}>
                            {day.slice(0, 3).toUpperCase()}
                        </div>

                        {/* Shifts Column */}
                        <div className={`flex-1 p-2 rounded-b-xl space-y-3 ${
                            hasShifts
                                ? 'bg-indigo-50 border-2 border-indigo-200'
                                : 'bg-gray-50 border-2 border-dashed border-gray-200'
                        }`}>
                            {hasShifts ? (
                                shiftGroups.map((group) => (
                                    <ShiftCard
                                        key={group.shiftKey}
                                        shiftName={group.displayName}
                                        timeRange={group.timeRange}
                                        assignments={group.assignments}
                                        onClick={onShiftClick}
                                    />
                                ))
                            ) : (
                                <div className="flex items-center justify-center h-full text-gray-400 text-xs">
                                    No shifts
                                </div>
                            )}
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

export default WeekGrid;
