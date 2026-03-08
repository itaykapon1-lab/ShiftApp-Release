// ========================================
// ADD SHIFT MODAL - Advanced Task Builder
// ========================================

import React, { useState, useEffect } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import Modal from '../common/Modal';

// ========================================
// DUMMY WEEK DATE MAPPING
// Maps day names to fixed ISO dates for a consistent reference week.
// Users see/select days, backend receives consistent anchor dates.
// ========================================
const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const DAY_TO_DATE_MAP = {
    'Sunday': '2026-01-04',
    'Monday': '2026-01-05',
    'Tuesday': '2026-01-06',
    'Wednesday': '2026-01-07',
    'Thursday': '2026-01-08',
    'Friday': '2026-01-09',
    'Saturday': '2026-01-10',
};

// Reverse map: Get day name from a date string
const dateToDayName = (dateStr) => {
    if (!dateStr) return 'Monday';
    const d = new Date(dateStr + 'T00:00:00');
    return DAYS_OF_WEEK[d.getDay()];
};

/**
 * Helper Component: Skill Builder for Requirements
 */
const SkillBuilder = ({ skills, onAddSkill, onRemoveSkill }) => {
    const [newSkillName, setNewSkillName] = useState('');
    const [newSkillLevel, setNewSkillLevel] = useState(5);

    const handleAdd = () => {
        if (newSkillName.trim()) {
            onAddSkill(newSkillName.trim(), newSkillLevel);
            setNewSkillName('');
            setNewSkillLevel(5);
        }
    };

    return (
        <div className="space-y-1">
            {/* Existing Skills */}
            <div className="flex flex-wrap gap-1 mb-2">
                {Object.entries(skills).map(([name, level]) => (
                    <div key={name} className="flex items-center gap-1 px-2 py-1 bg-blue-600 text-white rounded-full text-xs font-bold">
                        <span>{name} ≥ {level}</span>
                        <button onClick={() => onRemoveSkill(name)} className="hover:bg-blue-700 rounded-full p-0.5">
                            <X className="w-3 h-3" />
                        </button>
                    </div>
                ))}
            </div>

            {/* Add New Skill */}
            <div className="flex gap-1">
                <input
                    type="text"
                    value={newSkillName}
                    onChange={(e) => setNewSkillName(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleAdd()}
                    placeholder="Skill (e.g., Waiter)"
                    className="flex-1 px-2 py-1 border rounded text-xs"
                />
                <input
                    type="number"
                    min="1"
                    max="10"
                    value={newSkillLevel}
                    onChange={(e) => setNewSkillLevel(parseInt(e.target.value))}
                    className="w-12 px-1 py-1 border rounded text-xs text-center font-bold"
                />
                <button
                    onClick={handleAdd}
                    className="px-2 py-1 bg-blue-600 text-white rounded text-xs hover:bg-blue-700"
                >
                    <Plus className="w-3 h-3" />
                </button>
            </div>
        </div>
    );
};

/**
 * AddShiftModal Component
 * Complex Task/Option/Requirement hierarchy builder
 */
const AddShiftModal = ({ isOpen, onClose, onAdd, initialData = null }) => {
    const [name, setName] = useState('');
    const [day, setDay] = useState('Monday');
    const [timeRange, setTimeRange] = useState('08:00-16:00');

    // DATE ANCHORING FIX: Preserve the original date from the DB when editing.
    // This prevents the DAY_TO_DATE_MAP from clobbering imported dates (e.g., Feb 16 → Jan 5)
    const [originalDateStr, setOriginalDateStr] = useState(null); // e.g., "2026-02-16"

    // Advanced Structure: Tasks -> Options -> Requirements
    const [tasks, setTasks] = useState([{
        task_id: `task_${Date.now()}`,
        name: 'Main Task',
        options: [{
            preference_score: 0,
            priority: 1,
            requirements: [{
                count: 1,
                required_skills: {}
            }]
        }]
    }]);

    // Parse initialData for Edit Mode
    useEffect(() => {
        if (initialData) {
            setName(initialData.name || '');

            // Extract day and time from existing shift
            if (initialData.start_time && initialData.end_time) {
                const startDate = new Date(initialData.start_time);
                const endDate = new Date(initialData.end_time);

                // Extract TIME for display (HH:MM-HH:MM)
                const start = startDate.toTimeString().slice(0, 5);
                const end = endDate.toTimeString().slice(0, 5);
                setTimeRange(`${start}-${end}`);

                // Extract day name from the date for display
                const dayName = DAYS_OF_WEEK[startDate.getDay()];
                setDay(dayName);

                // DATE ANCHORING FIX: Store the original date string (YYYY-MM-DD)
                // from the actual DB value. This is the date that was imported from
                // Excel or previously saved. We MUST preserve it on update.
                // Extract date portion from the ISO string directly (avoid timezone shift)
                const isoStr = initialData.start_time;
                const anchored = isoStr.includes('T') ? isoStr.split('T')[0] : isoStr.slice(0, 10);
                setOriginalDateStr(anchored);
            }

            // Parse tasks_data (CRITICAL: Complex nested structure)
            const tasksData = initialData?.tasks_data?.tasks || [];
            if (tasksData.length > 0) {
                setTasks(tasksData);
            }
        } else {
            // Reset for Add Mode
            setName('');
            setTimeRange('08:00-16:00');
            setDay('Monday'); // Default to Monday for new shifts
            setOriginalDateStr(null); // No anchor in create mode

            setTasks([{
                task_id: `task_${Date.now()}`,
                name: 'Main Task',
                options: [{ preference_score: 0, priority: 1, requirements: [{ count: 1, required_skills: {} }] }]
            }]);
        }
    }, [initialData, isOpen]);

    const addTask = () => {
        setTasks(prev => [...prev, {
            task_id: `task_${Date.now()}`,
            name: `Task ${prev.length + 1}`,
            options: [{
                preference_score: 0,
                priority: 1,
                requirements: [{ count: 1, required_skills: {} }]
            }]
        }]);
    };

    // Helper to deep clone tasks array to prevent state mutation bugs
    const cloneTasks = (tasks) => structuredClone(tasks);

    const updateTaskName = (taskIdx, newName) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].name = newName;
            return copy;
        });
    };

    const removeTask = (taskIdx) => {
        setTasks(prev => prev.filter((_, i) => i !== taskIdx));
    };

    const addOption = (taskIdx) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options.push({
                preference_score: 0,
                priority: 1,
                requirements: [{ count: 1, required_skills: {} }]
            });
            return copy;
        });
    };

    const removeOption = (taskIdx, optIdx) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options = copy[taskIdx].options.filter((_, i) => i !== optIdx);
            return copy;
        });
    };

    const addRequirement = (taskIdx, optIdx) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options[optIdx].requirements.push({
                count: 1,
                required_skills: {}
            });
            return copy;
        });
    };

    const removeRequirement = (taskIdx, optIdx, reqIdx) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options[optIdx].requirements =
                copy[taskIdx].options[optIdx].requirements.filter((_, i) => i !== reqIdx);
            return copy;
        });
    };

    const updateOptionPriority = (taskIdx, optIdx, newPriority) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options[optIdx].priority = parseInt(newPriority);
            return copy;
        });
    };

    const updateRequirementCount = (taskIdx, optIdx, reqIdx, newCount) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options[optIdx].requirements[reqIdx].count = parseInt(newCount);
            return copy;
        });
    };

    const addSkillToRequirement = (taskIdx, optIdx, reqIdx, skillName, skillLevel) => {
        if (!skillName.trim()) return;
        setTasks(prev => {
            const copy = cloneTasks(prev);
            copy[taskIdx].options[optIdx].requirements[reqIdx].required_skills[skillName.trim()] = parseInt(skillLevel);
            return copy;
        });
    };

    const removeSkillFromRequirement = (taskIdx, optIdx, reqIdx, skillName) => {
        setTasks(prev => {
            const copy = cloneTasks(prev);
            delete copy[taskIdx].options[optIdx].requirements[reqIdx].required_skills[skillName];
            return copy;
        });
    };

    const handleSubmit = async () => {
        if (!name.trim()) {
            alert('Enter shift name');
            return;
        }

        // Validate: every task with 2+ options should have at least one #1 priority
        for (const task of tasks) {
            if (task.options.length > 1) {
                const hasPriority1 = task.options.some(opt => (opt.priority || 1) === 1);
                if (!hasPriority1) {
                    const proceed = confirm(
                        `Task "${task.name}" has no option set to Priority #1 (most preferred). ` +
                        `The solver will penalize all options equally. Continue anyway?`
                    );
                    if (!proceed) return;
                }
            }
        }

        // DATE ANCHORING FIX: Determine the correct date to use.
        // In EDIT mode: If the user hasn't changed the day, use the original date from the DB.
        //               If the user DID change the day, use the DAY_TO_DATE_MAP (new shift day).
        // In CREATE mode: Always use DAY_TO_DATE_MAP (no original date exists).
        let dateToUse;
        const isEdit = !!initialData;

        if (isEdit && originalDateStr) {
            // Check if the user changed the day dropdown from its original value
            const originalDay = initialData.start_time
                ? DAYS_OF_WEEK[new Date(initialData.start_time).getDay()]
                : null;

            if (day === originalDay) {
                // Day UNCHANGED → preserve the exact original date (critical for solver)
                dateToUse = originalDateStr;
            } else {
                // Day was EXPLICITLY changed by user → use dummy week mapping
                dateToUse = DAY_TO_DATE_MAP[day];
            }
        } else {
            // CREATE mode → use dummy week mapping
            dateToUse = DAY_TO_DATE_MAP[day];
        }

        // Convert string time range to two ISO datetimes
        const [startStr, endStr] = timeRange.split('-');
        const start_time = `${dateToUse}T${startStr}:00`;
        const end_time = `${dateToUse}T${endStr}:00`;

        const payload = {
            shift_id: initialData?.shift_id || `S${Date.now()}`,
            name: name.trim(),
            start_time: start_time,
            end_time: end_time,
            tasks_data: { tasks }
            // session_id is handled by backend via cookie - don't send hardcoded value
        };

        try {
            const result = await onAdd(payload, initialData?.shift_id);

            // Reset
            setName('');
            setTasks([{
                task_id: `task_${Date.now()}`,
                name: 'Main Task',
                options: [{ preference_score: 0, priority: 1, requirements: [{ count: 1, required_skills: {} }] }]
            }]);
            onClose();
        } catch (err) {
            console.error(initialData ? "❌ Failed to update shift:" : "❌ Failed to create shift:", err);
            alert((initialData ? 'Failed to update shift: ' : 'Failed to create shift: ') + err.message);
        }
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={initialData ? "🏗️ Edit Shift" : "🏗️ Advanced Shift Builder"} size="xl">
            <div className="space-y-6">
                {/* Shift Details */}
                <div className="bg-gradient-to-r from-indigo-50 to-purple-50 p-4 rounded-xl border-2 border-indigo-200">
                    <h3 className="font-bold text-lg mb-3 text-indigo-900">📋 Shift Details</h3>
                    <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Evening Service Shift"
                        className="w-full px-4 py-3 border-2 border-indigo-300 rounded-lg outline-none text-lg font-medium mb-3"
                    />
                    <div className="grid grid-cols-2 gap-3">
                        {/* Day Dropdown - Primary Input */}
                        <div>
                            <label className="block text-sm font-bold mb-1 text-gray-700">📅 Day of Week</label>
                            <select
                                value={day}
                                onChange={(e) => setDay(e.target.value)}
                                className="w-full px-3 py-2 border-2 border-indigo-300 rounded-lg font-medium bg-white cursor-pointer hover:border-indigo-400 transition-colors"
                            >
                                {DAYS_OF_WEEK.map((d) => (
                                    <option key={d} value={d}>{d}</option>
                                ))}
                            </select>
                        </div>

                        {/* Time Range */}
                        <div>
                            <label className="block text-sm font-bold mb-1 text-gray-700">⏰ Time Range</label>
                            <input
                                type="text"
                                value={timeRange}
                                onChange={(e) => setTimeRange(e.target.value)}
                                placeholder="18:00-23:00"
                                className="w-full px-3 py-2 border-2 border-gray-300 rounded-lg"
                            />
                        </div>
                    </div>
                </div>

                {/* Tasks List */}
                <div className="space-y-4">
                    <div className="flex justify-between items-center">
                        <h3 className="font-bold text-lg text-gray-800">🎯 Tasks (What needs to be done)</h3>
                        <button
                            onClick={addTask}
                            className="flex items-center px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 font-bold text-sm"
                        >
                            <Plus className="w-4 h-4 mr-1" /> Add Task
                        </button>
                    </div>

                    {tasks.map((task, taskIdx) => (
                        <div key={task.task_id} className="border-4 border-blue-300 rounded-xl p-4 bg-blue-50">
                            {/* Task Header */}
                            <div className="flex items-center gap-2 mb-3">
                                <span className="text-2xl">📦</span>
                                <input
                                    type="text"
                                    value={task.name}
                                    onChange={(e) => updateTaskName(taskIdx, e.target.value)}
                                    placeholder="Task Name (e.g., Service Staff)"
                                    className="flex-1 px-3 py-2 border-2 border-blue-400 rounded-lg font-bold"
                                />
                                <button
                                    onClick={() => removeTask(taskIdx)}
                                    className="text-red-600 hover:bg-red-100 p-2 rounded-lg"
                                >
                                    <Trash2 className="w-5 h-5" />
                                </button>
                            </div>

                            {/* Options (OR Logic) */}
                            <div className="ml-8 space-y-3">
                                <div className="flex justify-between items-center">
                                    <span className="text-sm font-bold text-purple-700">🔀 OPTIONS (Choose ONE to satisfy this task)</span>
                                    <button
                                        onClick={() => addOption(taskIdx)}
                                        className="px-2 py-1 bg-purple-600 text-white rounded text-xs hover:bg-purple-700 font-bold"
                                    >
                                        <Plus className="w-3 h-3 inline mr-1" /> Add Option
                                    </button>
                                </div>

                                {task.options.map((option, optIdx) => (
                                    <div key={optIdx} className="border-2 border-purple-300 rounded-lg p-3 bg-purple-50">
                                        {/* Option Header */}
                                        <div className="flex justify-between items-center mb-2">
                                            <span className="font-bold text-purple-900">Option {String.fromCharCode(65 + optIdx)}</span>
                                            <div className="flex items-center gap-2">
                                                {task.options.length > 1 && (
                                                    <div className="flex items-center gap-1">
                                                        <label
                                                            htmlFor={`priority-${taskIdx}-${optIdx}`}
                                                            className="text-xs font-bold text-purple-700"
                                                        >
                                                            Priority:
                                                        </label>
                                                        <select
                                                            id={`priority-${taskIdx}-${optIdx}`}
                                                            value={option.priority || 1}
                                                            onChange={(e) => updateOptionPriority(taskIdx, optIdx, e.target.value)}
                                                            className="px-2 py-1 border-2 border-purple-300 rounded text-xs font-bold bg-white"
                                                        >
                                                            {[1, 2, 3, 4, 5].map(p => (
                                                                <option key={p} value={p}>#{p}</option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                )}
                                                {task.options.length > 1 && (
                                                    <button
                                                        onClick={() => removeOption(taskIdx, optIdx)}
                                                        className="text-red-600 hover:bg-red-100 p-1 rounded"
                                                    >
                                                        <X className="w-4 h-4" />
                                                    </button>
                                                )}
                                            </div>
                                        </div>

                                        {/* Requirements (AND Logic) */}
                                        <div className="ml-6 space-y-2">
                                            <div className="flex justify-between items-center">
                                                <span className="text-xs font-bold text-orange-700">⚡ REQUIREMENTS (ALL must be met)</span>
                                                <button
                                                    onClick={() => addRequirement(taskIdx, optIdx)}
                                                    className="px-2 py-1 bg-orange-500 text-white rounded text-xs hover:bg-orange-600"
                                                >
                                                    <Plus className="w-3 h-3 inline" />
                                                </button>
                                            </div>

                                            {option.requirements.map((req, reqIdx) => (
                                                <div key={reqIdx} className="border-2 border-orange-300 rounded-lg p-2 bg-orange-50">
                                                    {/* Requirement: Count + Skills */}
                                                    <div className="flex items-start gap-2">
                                                        <div className="flex-shrink-0">
                                                            <label className="block text-xs font-bold text-gray-700 mb-1">Count</label>
                                                            <input
                                                                type="number"
                                                                min="1"
                                                                value={req.count}
                                                                onChange={(e) => updateRequirementCount(taskIdx, optIdx, reqIdx, e.target.value)}
                                                                className="w-16 px-2 py-1 border-2 border-orange-400 rounded text-center font-bold"
                                                            />
                                                        </div>

                                                        <div className="flex-1">
                                                            <label className="block text-xs font-bold text-gray-700 mb-1">Skills (Name + Min Level)</label>
                                                            <SkillBuilder
                                                                skills={req.required_skills}
                                                                onAddSkill={(name, level) => addSkillToRequirement(taskIdx, optIdx, reqIdx, name, level)}
                                                                onRemoveSkill={(name) => removeSkillFromRequirement(taskIdx, optIdx, reqIdx, name)}
                                                            />
                                                        </div>

                                                        {option.requirements.length > 1 && (
                                                            <button
                                                                onClick={() => removeRequirement(taskIdx, optIdx, reqIdx)}
                                                                className="text-red-600 hover:bg-red-100 p-1 rounded mt-5"
                                                            >
                                                                <Trash2 className="w-4 h-4" />
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>

                {/* Actions */}
                <div className="flex gap-3 pt-4 border-t-4 border-gray-300">
                    <button
                        onClick={onClose}
                        className="flex-1 px-4 py-3 border-2 rounded-lg hover:bg-gray-50 font-bold"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        className="flex-1 px-4 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg font-bold shadow-lg hover:scale-105 transition-all"
                    >
                        {initialData ? '💾 Save Changes' : '🚀 Create Shift with Complex Logic'}
                    </button>
                </div>
            </div>
        </Modal>
    );
};

export default AddShiftModal;
