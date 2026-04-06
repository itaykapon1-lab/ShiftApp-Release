// ========================================
// ADD WORKER MODAL - With Skill Normalization
// ========================================

import React, { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import Modal from '../common/Modal';

/**
 * Normalize skill name to Title Case
 * Example: "chef" -> "Chef", "sous CHEF" -> "Sous Chef"
 */
const normalizeSkillName = (name) => {
    return name
        .trim()
        .toLowerCase()
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
};

const getInitialWorkerFormState = (initialData = null) => {
    if (!initialData) {
        return {
            name: '',
            skills: {},
            availability: {},
        };
    }

    const parsedSkills = initialData?.attributes?.skills || {};
    const parsedAvailability = initialData?.attributes?.availability || {};

    return {
        name: initialData.name || '',
        skills: typeof parsedSkills === 'object' ? parsedSkills : {},
        availability: typeof parsedAvailability === 'object' ? parsedAvailability : {},
    };
};

const AddWorkerModal = ({ isOpen, onClose, onAdd, initialData = null }) => {
    const initialFormState = getInitialWorkerFormState(initialData);
    const [name, setName] = useState(initialFormState.name);
    const [skills, setSkills] = useState(initialFormState.skills);
    const [availability, setAvailability] = useState(initialFormState.availability);
    const [newSkillName, setNewSkillName] = useState('');
    const [newSkillLevel, setNewSkillLevel] = useState(5);

    /* eslint-disable react-hooks/set-state-in-effect */
    useEffect(() => {
        const nextFormState = getInitialWorkerFormState(initialData);
        setName(nextFormState.name);
        setSkills(nextFormState.skills);
        setAvailability(nextFormState.availability);
    }, [initialData, isOpen]);
    /* eslint-enable react-hooks/set-state-in-effect */

    const handleAddSkill = () => {
        if (!newSkillName.trim()) return;

        // CRITICAL: Normalize to Title Case before adding
        const normalizedName = normalizeSkillName(newSkillName);

        // Ensure level is an integer (1-10)
        const validatedLevel = Math.max(1, Math.min(10, parseInt(newSkillLevel)));

        setSkills(prev => ({ ...prev, [normalizedName]: validatedLevel }));
        setNewSkillName('');
        setNewSkillLevel(5);
    };

    const handleAddAvailability = (day, timeRange, preference = 'NEUTRAL') => {
        setAvailability(prev => ({
            ...prev,
            [day]: { timeRange, preference }
        }));
    };

    const handleSubmit = async () => {
        if (!name.trim()) {
            alert('Enter worker name');
            return;
        }

        // Validate all skills have integer levels
        const validatedSkills = {};
        for (const [skillName, level] of Object.entries(skills)) {
            validatedSkills[skillName] = parseInt(level);
        }

        const payload = {
            worker_id: initialData?.worker_id || `W${Date.now()}`,
            name: name.trim(),
            attributes: {
                skills: validatedSkills, // Send as Dict {Name: Level}
                availability: availability
            }
            // session_id is handled by backend via cookie - don't send hardcoded value
        };

        try {
            await onAdd(payload, initialData?.worker_id);

            // Reset form
            setName('');
            setSkills({});
            setAvailability({});
            onClose();
        } catch (err) {
            console.error(initialData ? "❌ Failed to update worker:" : "❌ Failed to create worker:", err);
            alert((initialData ? 'Failed to update worker: ' : 'Failed to create worker: ') + err.message);
        }
    };

    const days = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={initialData ? "Edit Worker" : "Add Worker"} size="lg">
            <div className="space-y-6">
                {/* Name */}
                <div>
                    <label className="block text-sm font-bold text-gray-700 mb-2">Worker Name *</label>
                    <input
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="John Doe"
                        className="w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none text-lg"
                    />
                </div>

                {/* Skills */}
                <div className="border-2 border-indigo-200 rounded-lg p-4 bg-indigo-50">
                    <label className="block text-sm font-bold text-gray-700 mb-3">Skills (Name + Level 1-10)</label>
                    <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
                        <input
                            type="text"
                            value={newSkillName}
                            onChange={(e) => setNewSkillName(e.target.value)}
                            onKeyPress={(e) => e.key === 'Enter' && handleAddSkill()}
                            placeholder="Chef"
                            className="w-full min-w-0 px-3 py-2 border rounded-lg outline-none sm:flex-1"
                        />
                        <div className="grid grid-cols-2 gap-2 sm:flex sm:w-auto sm:items-center">
                            <input
                                type="number"
                                min="1"
                                max="10"
                                value={newSkillLevel}
                                onChange={(e) => setNewSkillLevel(parseInt(e.target.value))}
                                className="w-full px-3 py-2 border rounded-lg outline-none text-center font-bold sm:w-24"
                            />
                            <button
                                onClick={handleAddSkill}
                                className="inline-flex w-full items-center justify-center px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 font-medium sm:w-auto"
                            >
                                <Plus className="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                    <div className="space-y-2 max-h-40 overflow-y-auto">
                        {Object.entries(skills).map(([skill, level]) => (
                            <div key={skill} className="flex justify-between items-center px-3 py-2 bg-white rounded-lg border-2 border-blue-200">
                                <span className="font-bold text-gray-800">{skill}</span>
                                <div className="flex items-center gap-3">
                                    <span className="px-3 py-1 bg-blue-600 text-white rounded-full text-sm font-bold">Lvl {level}</span>
                                    <button
                                        onClick={() => setSkills(prev => { const copy = { ...prev }; delete copy[skill]; return copy; })}
                                        className="text-red-600 hover:bg-red-100 p-1 rounded transition-all"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Availability with Preferences */}
                <div className="border-2 border-green-200 rounded-lg p-4 bg-green-50">
                    <label className="block text-sm font-bold text-gray-700 mb-3">Availability Windows & Preferences</label>
                    <div className="space-y-2">
                        {days.map(day => {
                            const availData = availability[day];
                            const isAvailable = !!availData;
                            const timeRange = availData?.timeRange || '08:00-16:00';
                            const preference = availData?.preference || 'NEUTRAL';

                            return (
                                <div key={day} className="bg-white rounded-lg p-2 border-2 border-gray-200">
                                    <div className="flex items-center gap-2 mb-1">
                                        <input
                                            type="checkbox"
                                            id={`day-${day}`}
                                            checked={isAvailable}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    handleAddAvailability(day, '08:00-16:00', 'NEUTRAL');
                                                } else {
                                                    setAvailability(prev => { const copy = { ...prev }; delete copy[day]; return copy; });
                                                }
                                            }}
                                            className="w-4 h-4 text-indigo-600"
                                        />
                                        <label htmlFor={`day-${day}`} className="text-sm font-bold text-gray-700 w-12">{day}</label>

                                        {isAvailable && (
                                            <>
                                                <input
                                                    type="text"
                                                    value={timeRange}
                                                    onChange={(e) => handleAddAvailability(day, e.target.value, preference)}
                                                    placeholder="08:00-16:00"
                                                    className="flex-1 px-2 py-1 border rounded text-xs"
                                                />
                                                <select
                                                    value={preference}
                                                    onChange={(e) => handleAddAvailability(day, timeRange, e.target.value)}
                                                    className={`px-2 py-1 rounded text-xs font-bold border-2 ${preference === 'HIGH' ? 'bg-green-100 border-green-500 text-green-800' :
                                                        preference === 'LOW' ? 'bg-red-100 border-red-500 text-red-800' :
                                                            'bg-gray-100 border-gray-400 text-gray-700'
                                                        }`}
                                                >
                                                    <option value="HIGH">👍 Prefer</option>
                                                    <option value="NEUTRAL">➖ Neutral</option>
                                                    <option value="LOW">👎 Avoid</option>
                                                </select>
                                            </>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Actions */}
                <div className="flex gap-3 pt-4 border-t-2">
                    <button
                        onClick={onClose}
                        className="flex-1 px-4 py-3 border-2 border-gray-300 rounded-lg hover:bg-gray-50 font-bold transition-all"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        className="flex-1 px-4 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg hover:from-indigo-700 hover:to-purple-700 font-bold shadow-lg transition-all"
                    >
                        {initialData ? 'Save Changes' : 'Create Worker'}
                    </button>
                </div>
            </div>
        </Modal>
    );
};

export default AddWorkerModal;
