// ========================================
// SHIFTS TAB - Shifts Table & Logic (FIXED)
// ========================================

import React, { useCallback, useMemo } from 'react';
import { CalendarPlus, Edit, Trash2, AlertCircle } from 'lucide-react';
import { HelpButton } from '../../help';

/**
 * Format shift time from start/end timestamps
 */
const formatShiftTime = (shift) => {
    try {
        if (shift.start_time && shift.end_time) {
            const start = new Date(shift.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const end = new Date(shift.end_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            return `${start} - ${end}`;
        }
        if (shift.time_window) {
            const start = new Date(shift.time_window.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const end = new Date(shift.time_window.end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            return `${start} - ${end}`;
        }
        return "N/A";
    } catch (err) {
        return "Error";
    }
};

/**
 * Format shift day from start_time
 * FIXED: Extract day name from actual timestamp
 */
const formatShiftDay = (shift) => {
    try {
        if (shift.start_time) {
            const date = new Date(shift.start_time);
            const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
            return days[date.getDay()];
        }
        if (shift.time_window?.start) {
            const date = new Date(shift.time_window.start);
            const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
            return days[date.getDay()];
        }
        return "N/A";
    } catch (err) {
        return "N/A";
    }
};

/**
 * Format shift requirements from tasks_data
 * FIXED: Correctly parse the nested tasks array structure
 */
const formatShiftNeeds = (shift) => {
    try {
        // Access tasks_data correctly
        const tasksData = shift?.tasks_data;

        if (!tasksData) {
            return 'No tasks defined';
        }

        // Handle both formats: {tasks: [...]} or direct array
        let tasksList = [];
        if (tasksData.tasks && Array.isArray(tasksData.tasks)) {
            tasksList = tasksData.tasks;
        } else if (Array.isArray(tasksData)) {
            tasksList = tasksData;
        }

        if (tasksList.length === 0) {
            return 'No tasks defined';
        }

        // Count total requirements across all tasks
        let totalRequirements = 0;
        tasksList.forEach(task => {
            if (task.options && Array.isArray(task.options)) {
                task.options.forEach(option => {
                    if (option.requirements && Array.isArray(option.requirements)) {
                        totalRequirements += option.requirements.length;
                    }
                });
            }
        });

        // Return a summary
        if (tasksList.length === 1 && totalRequirements === 1) {
            return `1 task, 1 requirement`;
        } else if (tasksList.length === 1) {
            return `1 task, ${totalRequirements} requirements`;
        } else {
            return `${tasksList.length} tasks, ${totalRequirements} requirements`;
        }
    } catch (err) {
        console.error('Error formatting shift needs:', err);
        return "Error";
    }
};

/**
 * ShiftsTab Component
 */
const ShiftsTab = ({ shifts, onAddShift, onEditShift, onDeleteShift }) => {
    const duplicateNamesByDay = useMemo(() => {
        const counts = {};

        shifts.forEach((shift) => {
            const day = formatShiftDay(shift);
            const name = shift.name || 'Unnamed';
            const key = `${day}::${name}`;
            counts[key] = (counts[key] || 0) + 1;
        });

        return counts;
    }, [shifts]);

    const getShiftDisplayName = useCallback((shift) => {
        const day = formatShiftDay(shift);
        const name = shift.name || 'Unnamed';
        const key = `${day}::${name}`;

        if ((duplicateNamesByDay[key] || 0) > 1) {
            return `${name} (${formatShiftTime(shift)})`;
        }

        return name;
    }, [duplicateNamesByDay]);

    const handleDelete = async (shift) => {
        const timeInfo = formatShiftTime(shift);
        const displayName = getShiftDisplayName(shift);
        const confirmed = window.confirm(`Are you sure you want to delete "${displayName}" (${timeInfo})?`);
        if (!confirmed) return;

        try {
            await onDeleteShift(shift.shift_id);
        } catch (err) {
            alert(`Failed to delete shift: ${err.message}`);
        }
    };

    return (
        <div>
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h2 className="text-3xl font-black text-gray-800">Shifts Schedule</h2>
                    <p className="text-gray-600 mt-1">Manage shift timings and requirements</p>
                </div>
                <div className="flex items-center gap-2">
                    <HelpButton topicId="shifts.overview" label="Help" />
                    <button
                        onClick={onAddShift}
                        className="flex items-center px-6 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl font-black shadow-2xl hover:shadow-3xl transition-all hover:scale-105"
                    >
                        <CalendarPlus className="w-5 h-5 mr-2" />
                        Add Shift
                    </button>
                </div>
            </div>

            {shifts.length === 0 ? (
                <div className="text-center py-24 bg-gradient-to-br from-gray-50 to-purple-50 rounded-2xl border-4 border-dashed border-gray-300">
                    <AlertCircle className="w-20 h-20 mx-auto mb-6 opacity-30 text-gray-500" />
                    <p className="text-2xl font-bold text-gray-600 mb-2">No Shifts Found</p>
                    <p className="text-gray-500">Import an Excel file or add shifts manually</p>
                </div>
            ) : (
                <div className="overflow-x-auto rounded-2xl border-4 border-gray-200 shadow-xl">
                    <table className="w-full">
                        <thead className="bg-gradient-to-r from-purple-600 to-pink-600 text-white">
                            <tr className="text-sm font-black uppercase tracking-wider">
                                {/* REMOVED: ID column - internal use only */}
                                <th className="py-5 px-6 text-left">Name</th>
                                <th className="py-5 px-6 text-left">Day</th>
                                <th className="py-5 px-6 text-left">Time</th>
                                <th className="py-5 px-6 text-left">Requirements</th>
                                <th className="py-5 px-6 text-left">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y-2 divide-gray-200">
                            {shifts.map((s, idx) => (
                                <tr
                                    key={s.shift_id || idx}
                                    className="hover:bg-gradient-to-r hover:from-purple-50 hover:to-pink-50 transition-all"
                                >
                                    {/* REMOVED: ID column */}
                                    <td className="py-5 px-6 font-black text-lg text-gray-900">
                                        {getShiftDisplayName(s)}
                                    </td>
                                    <td className="py-5 px-6">
                                        <span className="px-3 py-1 bg-gradient-to-r from-indigo-500 to-blue-500 text-white rounded-full text-sm font-bold shadow-md">
                                            {formatShiftDay(s)}
                                        </span>
                                    </td>
                                    <td className="py-5 px-6 text-sm text-gray-700 font-medium">
                                        {formatShiftTime(s)}
                                    </td>
                                    <td className="py-5 px-6 text-sm text-gray-600">
                                        {formatShiftNeeds(s)}
                                    </td>
                                    <td className="py-5 px-6">
                                        <div className="flex gap-2">
                                            <button
                                                onClick={() => onEditShift(s)}
                                                className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-all font-bold text-sm shadow-md hover:shadow-lg"
                                            >
                                                <Edit className="w-4 h-4" />
                                                Edit
                                            </button>
                                            <button
                                                onClick={() => handleDelete(s)}
                                                className="flex items-center gap-2 px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-all font-bold text-sm shadow-md hover:shadow-lg"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                                Delete
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

export default ShiftsTab;
