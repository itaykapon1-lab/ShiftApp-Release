/**
 * @module constraints/components/WorkerSelect
 * @description Searchable dropdown for selecting a worker from the available pool.
 *   Opens a filterable list on click and notifies the parent via onChange.
 *   When multiple workers share the same display name, a short ID suffix is
 *   appended for visual disambiguation (e.g. "David Cohen (4f2a)").
 */

import React, { useState, useMemo, useCallback } from 'react';

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
 * @param {Object} props
 * @param {string} props.value - Currently selected worker ID
 * @param {function} props.onChange - Callback when a worker is selected
 * @param {Object[]} props.workers - Available workers array
 * @param {string} [props.placeholder='Select worker...'] - Placeholder text
 * @param {string} [props.id] - HTML id attribute
 */
const WorkerSelect = React.memo(({ value, onChange, workers, placeholder = 'Select worker...', id }) => {
    const [search, setSearch] = useState('');
    const [isOpen, setIsOpen] = useState(false);

    // Detect which names appear more than once so we can disambiguate
    const duplicateNames = useMemo(() => {
        const counts = {};
        workers.forEach(w => {
            counts[w.name] = (counts[w.name] || 0) + 1;
        });
        const dupes = new Set();
        Object.entries(counts).forEach(([name, count]) => {
            if (count > 1) dupes.add(name);
        });
        return dupes;
    }, [workers]);

    const getDisplayLabel = useCallback((worker) => {
        if (duplicateNames.has(worker.name)) {
            return `${worker.name} (${shortIdSuffix(worker.worker_id)})`;
        }
        return worker.name;
    }, [duplicateNames]);

    const selectedWorker = useMemo(
        () => workers.find(w => w.worker_id === value),
        [workers, value]
    );

    const filteredWorkers = useMemo(() => {
        if (!search) return workers;
        const lower = search.toLowerCase();
        return workers.filter(w => w.name.toLowerCase().includes(lower));
    }, [workers, search]);

    const handleSelect = useCallback((workerId) => {
        onChange(workerId);
        setIsOpen(false);
        setSearch('');
    }, [onChange]);

    return (
        <div className="relative">
            <div
                className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg cursor-pointer bg-white flex justify-between items-center"
                onClick={() => setIsOpen(!isOpen)}
            >
                <span className={selectedWorker ? 'text-gray-900' : 'text-gray-400'}>
                    {selectedWorker ? getDisplayLabel(selectedWorker) : placeholder}
                </span>
                <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </div>

            {isOpen && (
                <div className="absolute z-50 w-full mt-1 bg-white border-2 border-gray-200 rounded-lg shadow-lg max-h-60 overflow-hidden">
                    <div className="p-2 border-b">
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search workers..."
                            className="w-full px-3 py-2 border border-gray-200 rounded focus:outline-none focus:border-cyan-500"
                            autoFocus
                        />
                    </div>
                    <div className="max-h-48 overflow-y-auto">
                        {filteredWorkers.length === 0 ? (
                            <div className="px-3 py-2 text-gray-500 text-sm">No workers found</div>
                        ) : (
                            filteredWorkers.map(worker => (
                                <div
                                    key={worker.worker_id}
                                    className={`px-3 py-2 cursor-pointer hover:bg-cyan-50 ${
                                        worker.worker_id === value ? 'bg-cyan-100 font-medium' : ''
                                    }`}
                                    onClick={() => handleSelect(worker.worker_id)}
                                >
                                    {getDisplayLabel(worker)}
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    );
});

WorkerSelect.displayName = 'WorkerSelect';

export default WorkerSelect;
