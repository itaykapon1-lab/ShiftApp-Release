// ========================================
// WORKERS TAB - Workers Table & Logic (FIXED)
// ========================================

import React, { useState } from 'react';
import { UserPlus, Edit, Trash2, AlertCircle } from 'lucide-react';
import Modal from '../common/Modal';
import { HelpButton } from '../../help';

/**
 * Extract and format worker skills
 */
const getWorkerSkills = (worker) => {
    try {
        const skillsData = worker?.attributes?.skills || worker?.skills;
        if (!skillsData) return [];

        if (Array.isArray(skillsData)) return skillsData;
        if (typeof skillsData === 'object') {
            return Object.entries(skillsData).map(([name, lvl]) => `${name} (${lvl})`);
        }
        return [];
    } catch (err) {
        return [];
    }
};

/**
 * Render availability with preferences
 * FIXED: Correctly accesses nested attributes.availability structure
 */
const renderAvailabilityWithPreferences = (worker) => {
    try {
        // CRITICAL FIX: Access availability from correct nested path
        const avail = worker?.attributes?.availability || {};

        // Validate it's an object
        if (typeof avail !== 'object' || avail === null || Array.isArray(avail)) {
            return <span className="text-gray-400 italic text-sm">No availability</span>;
        }

        const entries = Object.entries(avail);
        if (entries.length === 0) {
            return <span className="text-gray-400 italic text-sm">No availability</span>;
        }

        return (
            <div className="flex flex-wrap gap-1">
                {entries.map(([day, data]) => {
                    // Handle both string and object formats
                    const timeRange = typeof data === 'string' ? data : data?.timeRange || '08:00-16:00';
                    const preference = typeof data === 'object' ? data?.preference || 'NEUTRAL' : 'NEUTRAL';

                    let badgeClasses = 'px-2 py-1 rounded-full text-xs font-bold flex items-center gap-1';
                    let icon = '';
                    let colorClasses = '';

                    if (preference === 'HIGH') {
                        colorClasses = 'bg-green-100 border-2 border-green-500 text-green-800';
                        icon = '👍';
                    } else if (preference === 'LOW') {
                        colorClasses = 'bg-red-100 border-2 border-red-500 text-red-800';
                        icon = '👎';
                    } else {
                        colorClasses = 'bg-gray-100 border-2 border-gray-300 text-gray-700';
                        icon = '➖';
                    }

                    return (
                        <div
                            key={day}
                            className={`${badgeClasses} ${colorClasses}`}
                            title={`${day}: ${timeRange} (${preference})`}
                        >
                            <span>{icon}</span>
                            <span>{day}</span>
                        </div>
                    );
                })}
            </div>
        );
    } catch (err) {
        console.error('Error rendering availability:', err);
        return <span className="text-red-400 text-sm">Error</span>;
    }
};

/**
 * Derives a short suffix from a worker_id for duplicate-name disambiguation.
 * Uses the last 4 characters of the ID (after the last hyphen, if present).
 */
const shortIdSuffix = (workerId) => {
    if (!workerId) return '';
    const parts = workerId.split('-');
    const last = parts[parts.length - 1];
    return last.slice(-4);
};

/**
 * Builds a Set of worker names that appear more than once in the list.
 */
const buildDuplicateNameSet = (workers) => {
    const counts = {};
    workers.forEach(w => { counts[w.name] = (counts[w.name] || 0) + 1; });
    const dupes = new Set();
    Object.entries(counts).forEach(([name, count]) => {
        if (count > 1) dupes.add(name);
    });
    return dupes;
};

/**
 * WorkersTab Component
 * @param {Object} props
 * @param {Array} props.workers - List of workers
 * @param {Function} props.onAddWorker - Callback to add a worker
 * @param {Function} props.onEditWorker - Callback to edit a worker
 * @param {Function} props.onDeleteWorker - Callback to delete a worker
 * @param {Function} props.showToast - Callback to show toast notifications
 */
const WorkersTab = ({ workers, onAddWorker, onEditWorker, onDeleteWorker, showToast }) => {
    const [deleteConfirm, setDeleteConfirm] = useState({ open: false, worker: null });
    const [isDeleting, setIsDeleting] = useState(false);

    // Detect which names appear more than once for visual disambiguation
    const duplicateNames = buildDuplicateNameSet(workers);

    const handleDeleteClick = (worker) => {
        setDeleteConfirm({ open: true, worker });
    };

    const handleDeleteConfirm = async () => {
        if (!deleteConfirm.worker) return;

        setIsDeleting(true);
        try {
            await onDeleteWorker(deleteConfirm.worker.worker_id);
            showToast?.('success', 'Worker Deleted', `${deleteConfirm.worker.name} has been removed.`);
        } catch (err) {
            showToast?.('error', 'Delete Failed', err.message || 'Could not delete worker.');
        } finally {
            setIsDeleting(false);
            setDeleteConfirm({ open: false, worker: null });
        }
    };

    const handleDeleteCancel = () => {
        setDeleteConfirm({ open: false, worker: null });
    };

    return (
        <div>
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h2 className="text-3xl font-black text-gray-800">Workers Database</h2>
                    <p className="text-gray-600 mt-1">Manage employee profiles and skills</p>
                </div>
                <div className="flex items-center gap-2">
                    <HelpButton topicId="workers.overview" label="Help" />
                    <button
                        onClick={onAddWorker}
                        className="flex items-center px-6 py-3 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-xl font-black shadow-2xl hover:shadow-3xl transition-all hover:scale-105"
                    >
                        <UserPlus className="w-5 h-5 mr-2" />
                        Add Worker
                    </button>
                </div>
            </div>

            {workers.length === 0 ? (
                <div className="text-center py-24 bg-gradient-to-br from-gray-50 to-blue-50 rounded-2xl border-4 border-dashed border-gray-300">
                    <AlertCircle className="w-20 h-20 mx-auto mb-6 opacity-30 text-gray-500" />
                    <p className="text-2xl font-bold text-gray-600 mb-2">No Workers Found</p>
                    <p className="text-gray-500">Import an Excel file or add workers manually</p>
                </div>
            ) : (
                <div className="overflow-x-auto rounded-2xl border-4 border-gray-200 shadow-xl">
                    <table className="w-full">
                        <thead className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white">
                            <tr className="text-sm font-black uppercase tracking-wider">
                                {/* REMOVED: ID column - internal use only */}
                                <th className="py-5 px-6 text-left">Name</th>
                                <th className="py-5 px-6 text-left">Skills</th>
                                <th className="py-5 px-6 text-left">Availability</th>
                                <th className="py-5 px-6 text-left">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y-2 divide-gray-200">
                            {workers.map((w, idx) => {
                                const skills = getWorkerSkills(w);
                                return (
                                    <tr
                                        key={w.worker_id || idx}
                                        className="hover:bg-gradient-to-r hover:from-indigo-50 hover:to-purple-50 transition-all"
                                    >
                                        {/* REMOVED: ID column */}
                                        <td className="py-5 px-6 font-black text-lg text-gray-900">
                                            {w.name || 'Unnamed'}
                                            {duplicateNames.has(w.name) && (
                                                <span
                                                    className="ml-2 px-1.5 py-0.5 text-xs font-mono font-medium text-gray-400 bg-gray-100 border border-gray-200 rounded select-none"
                                                    title={`Worker ID: ${w.worker_id}`}
                                                >
                                                    #{shortIdSuffix(w.worker_id)}
                                                </span>
                                            )}
                                        </td>
                                        <td className="py-5 px-6">
                                            <div className="flex gap-2 flex-wrap">
                                                {skills.length > 0 ? (
                                                    skills.map((skill, i) => (
                                                        <span
                                                            key={i}
                                                            className="px-3 py-1.5 bg-gradient-to-r from-blue-500 to-cyan-500 text-white rounded-full text-xs font-bold shadow-md"
                                                        >
                                                            {skill}
                                                        </span>
                                                    ))
                                                ) : (
                                                    <span className="text-gray-400 italic text-sm">No skills</span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="py-5 px-6">
                                            {renderAvailabilityWithPreferences(w)}
                                        </td>
                                        <td className="py-5 px-6">
                                            <div className="flex gap-2">
                                                <button
                                                    onClick={() => onEditWorker(w)}
                                                    className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-all font-bold text-sm shadow-md hover:shadow-lg"
                                                >
                                                    <Edit className="w-4 h-4" />
                                                    Edit
                                                </button>
                                                <button
                                                    onClick={() => handleDeleteClick(w)}
                                                    className="flex items-center gap-2 px-3 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-all font-bold text-sm shadow-md hover:shadow-lg"
                                                >
                                                    <Trash2 className="w-4 h-4" />
                                                    Delete
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Delete Confirmation Modal */}
            <Modal
                isOpen={deleteConfirm.open}
                onClose={handleDeleteCancel}
                title="Confirm Delete"
            >
                <div className="text-center">
                    <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-red-100 mb-4">
                        <Trash2 className="h-6 w-6 text-red-600" />
                    </div>
                    <h3 className="text-lg font-medium text-gray-900 mb-2">
                        Delete Worker
                    </h3>
                    <p className="text-gray-500 mb-6">
                        Are you sure you want to delete <strong>{deleteConfirm.worker?.name}</strong>?
                        This action cannot be undone.
                    </p>
                    <div className="flex gap-3 justify-center">
                        <button
                            onClick={handleDeleteCancel}
                            className="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition-colors font-medium"
                            disabled={isDeleting}
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleDeleteConfirm}
                            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-medium disabled:opacity-50"
                            disabled={isDeleting}
                        >
                            {isDeleting ? 'Deleting...' : 'Delete'}
                        </button>
                    </div>
                </div>
            </Modal>
        </div>
    );
};

export default WorkersTab;
