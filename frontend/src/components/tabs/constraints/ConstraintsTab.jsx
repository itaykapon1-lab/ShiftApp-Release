/**
 * @module constraints/ConstraintsTab
 * @description Root orchestrator for the Constraints tab. Manages all constraint
 *   state (instances, schemas, save status, dirty tracking), delegates rendering
 *   to focused sub-components, and handles API interactions.
 *
 *   Bug fixes applied during extraction:
 *   - BUG 1: Race condition in saveConstraints — functional snapshot updater
 *   - BUG 2: Inefficient dirty tracking — useMemo dirtyInstanceIds Set
 *   - BUG 3: Unstable callback references — functional state updaters
 */

import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { Shield, Settings, RefreshCw } from 'lucide-react';
import { updateConstraints, getConstraints, getConstraintSchema } from '../../../api/endpoints';
import { buildErrorMap } from '../../../utils/constraintErrorMapping';
import { HelpButton, HelpPopover } from '../../../help';

import {
    normalizeConstraintKind,
    toInstance,
    toApiConstraint,
    serializeInstance,
    buildSnapshotMap,
} from './utils/constraintHelpers';
import AddConstraintPanel from './components/AddConstraintPanel';
import ConstraintCard from './components/ConstraintCard';

function normalizeSchemaResponse(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.schemas)) return payload.schemas;
    if (Array.isArray(payload?.data)) return payload.data;
    return [];
}

/**
 * @param {Object} props
 * @param {Object[]} props.constraints - Constraints from parent (API format)
 * @param {function} [props.onConstraintsReplace] - Callback to replace parent constraints
 * @param {Object[]} props.workers - Available workers
 * @param {function} [props.onRefresh] - Callback after data refresh
 */
const ConstraintsTab = ({ constraints: propConstraints, onConstraintsReplace, workers, onRefresh }) => {
    const [schemas, setSchemas] = useState([]);
    const [instances, setInstances] = useState([]);
    const [loading, setLoading] = useState(true);
    // BUG 1 FIX: Track concurrent saves with a Set instead of a single ID
    const [savingInstanceIds, setSavingInstanceIds] = useState(new Set());
    const [error, setError] = useState(null);
    const [errorMapByInstanceId, setErrorMapByInstanceId] = useState({});
    const [saveStateByInstanceId, setSaveStateByInstanceId] = useState({});
    const [savedSnapshotById, setSavedSnapshotById] = useState({});

    // BUG 3 FIX: Ref to current instances for callbacks that need the value
    // without adding it to the dependency array (keeps callbacks stable)
    const instancesRef = useRef(instances);
    instancesRef.current = instances;

    // Unmount guard for async operations
    const mountedRef = useRef(false);
    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    useEffect(() => {
        async function loadSchema() {
            try {
                const data = await getConstraintSchema();
                const normalized = normalizeSchemaResponse(data);
                if (mountedRef.current) {
                    setSchemas(normalized);
                }
            } catch (err) {
                console.error('Failed to load constraint schema:', err);
                if (mountedRef.current) {
                    setError('Failed to load constraint schema');
                }
            }
        }
        loadSchema();
    }, []);

    useEffect(() => {
        if (propConstraints) {
            const insts = propConstraints.map(toInstance);
            setInstances(insts);
            setSavedSnapshotById(buildSnapshotMap(insts));
            setErrorMapByInstanceId({});
            setSaveStateByInstanceId({});
            setLoading(false);
        }
    }, [propConstraints]);

    // BUG 2 FIX: Pre-compute dirty IDs once per state change instead of
    // calling JSON.stringify per-instance during render
    const dirtyInstanceIds = useMemo(() => {
        const dirty = new Set();
        instances.forEach(inst => {
            if (savedSnapshotById[inst.id] !== serializeInstance(inst)) {
                dirty.add(inst.id);
            }
        });
        return dirty;
    }, [instances, savedSnapshotById]);

    const saveConstraints = useCallback(async (insts, sourceInstanceId) => {
        if (!sourceInstanceId) return;

        // BUG 1 FIX: Add to saving set instead of replacing single ID
        setSavingInstanceIds(prev => new Set(prev).add(sourceInstanceId));
        setSaveStateByInstanceId(prev => ({
            ...prev,
            [sourceInstanceId]: { status: 'saving', message: '' },
        }));

        const apiConstraints = insts.map(toApiConstraint);

        try {
            await updateConstraints(apiConstraints);

            if (!mountedRef.current) return;

            if (onConstraintsReplace) {
                onConstraintsReplace(apiConstraints);
            }

            // BUG 1 FIX: Only update the snapshot for the saved instance,
            // using functional updater to avoid stale closure data
            setSavedSnapshotById(prev => {
                const savedInst = insts.find(i => i.id === sourceInstanceId);
                if (!savedInst) return prev;
                return {
                    ...prev,
                    [sourceInstanceId]: serializeInstance(savedInst),
                };
            });
            setErrorMapByInstanceId(prev => ({
                ...prev,
                [sourceInstanceId]: {},
            }));
            setSaveStateByInstanceId(prev => ({
                ...prev,
                [sourceInstanceId]: { status: 'success', message: 'Saved' },
            }));
        } catch (err) {
            if (!mountedRef.current) return;

            const detail = err?.data?.detail;
            if (err?.status === 422 && Array.isArray(detail)) {
                const errorMapById = buildErrorMap(insts, detail);
                setErrorMapByInstanceId(errorMapById);
                const firstFieldError = Object.values(errorMapById[sourceInstanceId] || {})[0];
                setSaveStateByInstanceId(prev => ({
                    ...prev,
                    [sourceInstanceId]: {
                        status: 'error',
                        message: firstFieldError || 'Validation failed. Please complete required fields.',
                    },
                }));
            } else {
                setError(`Failed to save: ${err.message}`);
                setSaveStateByInstanceId(prev => ({
                    ...prev,
                    [sourceInstanceId]: {
                        status: 'error',
                        message: err?.message || 'Failed to save constraint',
                    },
                }));
            }
        } finally {
            if (mountedRef.current) {
                // BUG 1 FIX: Remove from saving set
                setSavingInstanceIds(prev => {
                    const next = new Set(prev);
                    next.delete(sourceInstanceId);
                    return next;
                });
            }
        }
    }, [onConstraintsReplace]);

    // BUG 3 FIX: Functional state updaters — no [instances] dependency
    const handleAdd = useCallback((inst) => {
        setInstances(prev => [...prev, inst]);
        setSaveStateByInstanceId(prev => ({
            ...prev,
            [inst.id]: { status: 'idle', message: '' },
        }));
    }, []);

    const handleUpdate = useCallback((updated) => {
        setInstances(prev => prev.map(i => i.id === updated.id ? updated : i));
        setErrorMapByInstanceId(prev => ({
            ...prev,
            [updated.id]: {},
        }));
        setSaveStateByInstanceId(prev => ({
            ...prev,
            [updated.id]: { status: 'idle', message: '' },
        }));
    }, []);

    // handleSave needs current instances for the API call — use ref
    const handleSave = useCallback((id) => {
        saveConstraints(instancesRef.current, id);
    }, [saveConstraints]);

    const handleRemove = useCallback((id) => {
        if (!window.confirm('Are you sure you want to remove this constraint?')) return;
        const currentInstances = instancesRef.current;
        const next = currentInstances.filter(i => i.id !== id);
        setInstances(next);

        setErrorMapByInstanceId(prev => {
            const { [id]: _removed, ...rest } = prev;
            return rest;
        });
        setSaveStateByInstanceId(prev => {
            const { [id]: _removed, ...rest } = prev;
            return rest;
        });
        setSavedSnapshotById(prev => {
            const { [id]: _removed, ...rest } = prev;
            return rest;
        });

        saveConstraints(next, id);
    }, [saveConstraints]);

    // BUG 3 FIX: Functional state updater — no [instances] dependency
    const handleToggle = useCallback((id) => {
        setInstances(prev => prev.map(i =>
            i.id === id ? { ...i, enabled: !i.enabled } : i
        ));
        setSaveStateByInstanceId(prev => ({
            ...prev,
            [id]: { status: 'idle', message: '' },
        }));
    }, []);

    const handleRefresh = useCallback(async () => {
        setLoading(true);
        try {
            const data = await getConstraints();
            if (!mountedRef.current) return;
            const insts = (data.constraints || []).map(toInstance);
            setInstances(insts);
            setSavedSnapshotById(buildSnapshotMap(insts));
            setErrorMapByInstanceId({});
            setSaveStateByInstanceId({});
            if (onRefresh) onRefresh();
        } catch {
            if (mountedRef.current) {
                setError('Failed to refresh constraints');
            }
        } finally {
            if (mountedRef.current) {
                setLoading(false);
            }
        }
    }, [onRefresh]);

    const schemaByTypeKey = useMemo(() => {
        const map = new Map();
        schemas.forEach((schema) => {
            const normalizedKey = String(schema?.key ?? schema?.category ?? '')
                .trim()
                .toLowerCase();
            if (normalizedKey) {
                map.set(normalizedKey, schema);
            }
        });
        return map;
    }, [schemas]);

    const getSchemaForInstance = useCallback((inst) => {
        const normalizedTypeKey = String(inst?.typeKey ?? '')
            .trim()
            .toLowerCase();
        return normalizedTypeKey ? schemaByTypeKey.get(normalizedTypeKey) : undefined;
    }, [schemaByTypeKey]);

    const { staticConstraints, dynamicConstraints } = useMemo(() => {
        const dynamicTypeKeys = new Set(['mutual_exclusion', 'colocation']);
        const nextStatic = [];
        const nextDynamic = [];

        instances.forEach((inst) => {
            const normalizedTypeKey = String(inst?.typeKey ?? '')
                .trim()
                .toLowerCase();
            const schema = normalizedTypeKey ? schemaByTypeKey.get(normalizedTypeKey) : undefined;
            const rawKind = schema?.constraint_kind ?? inst?.constraintKind ?? inst?.constraint_kind ?? inst?.kind;
            const normalizedKind = normalizeConstraintKind(rawKind);
            const hasWorkerPairParams = Boolean(inst?.params?.worker_a_id || inst?.params?.worker_b_id);

            const isDynamic =
                normalizedKind === 'DYNAMIC' ||
                (normalizedKind !== 'STATIC' && (dynamicTypeKeys.has(normalizedTypeKey) || hasWorkerPairParams));

            if (isDynamic) {
                nextDynamic.push(inst);
            } else {
                nextStatic.push(inst);
            }
        });

        return {
            staticConstraints: nextStatic,
            dynamicConstraints: nextDynamic,
        };
    }, [instances, schemaByTypeKey]);

    // Derived: is anything currently saving?
    const isAnySaving = savingInstanceIds.size > 0;

    if (loading) {
        return (
            <div className="p-6 rounded-xl border-2 border-cyan-200 bg-cyan-50">
                <p className="text-cyan-800">Loading constraints...</p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-2xl font-black text-gray-800">Constraint Configuration</h2>
                    <p className="text-sm text-gray-600 mt-1">Control feasibility and preference tradeoffs</p>
                </div>
                <HelpButton topicId="constraints.logic" label="Help" />
            </div>

            {error && (
                <div className="p-4 bg-red-50 border-2 border-red-200 rounded-xl text-red-800">
                    {error}
                    <button
                        onClick={() => setError(null)}
                        className="ml-4 text-red-600 underline"
                    >
                        Dismiss
                    </button>
                </div>
            )}

            <AddConstraintPanel schemas={schemas} onAdd={handleAdd} />

            <div className="bg-white p-6 rounded-xl border-2 border-gray-200 shadow-lg">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2">
                        <Settings className="w-6 h-6" />
                        Global Settings
                        <HelpPopover hintId="static_constraint" />
                    </h3>
                    <button
                        onClick={handleRefresh}
                        disabled={isAnySaving}
                        className="p-2 text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
                        title="Refresh constraints"
                    >
                        <RefreshCw className={`w-5 h-5 ${isAnySaving ? 'animate-spin' : ''}`} />
                    </button>
                </div>

                <div className="space-y-3">
                    {staticConstraints.length === 0 ? (
                        <p className="text-gray-500 text-center py-4">No global constraints configured</p>
                    ) : (
                        staticConstraints.map(inst => {
                            const schema = getSchemaForInstance(inst);
                            return (
                                <ConstraintCard
                                    key={inst.id}
                                    instance={inst}
                                    schema={schema}
                                    workers={workers}
                                    onChange={handleUpdate}
                                    onRemove={handleRemove}
                                    onToggle={handleToggle}
                                    onSave={handleSave}
                                    isDirty={dirtyInstanceIds.has(inst.id)}
                                    isSaving={savingInstanceIds.has(inst.id)}
                                    saveStatus={saveStateByInstanceId[inst.id]?.status}
                                    saveMessage={saveStateByInstanceId[inst.id]?.message}
                                    errorMap={errorMapByInstanceId[inst.id] || {}}
                                />
                            );
                        })
                    )}
                </div>
            </div>

            <div className="bg-white p-6 rounded-xl border-2 border-gray-200 shadow-lg">
                <h3 className="text-xl font-bold text-gray-800 flex items-center gap-2 mb-4">
                    <Shield className="w-6 h-6" />
                    Worker Rules
                    <HelpPopover hintId="dynamic_constraint" />
                </h3>

                <div className="space-y-3">
                    {dynamicConstraints.length === 0 ? (
                        <div className="text-center py-8 text-gray-400">
                            <Shield className="w-12 h-12 mx-auto mb-3 opacity-30" />
                            <p className="font-medium">No worker rules defined</p>
                            <p className="text-sm">Use "Add a constraint" above to create mutual exclusion or co-location rules</p>
                        </div>
                    ) : (
                        dynamicConstraints.map(inst => {
                            const schema = getSchemaForInstance(inst);
                            return (
                                <ConstraintCard
                                    key={inst.id}
                                    instance={inst}
                                    schema={schema}
                                    workers={workers}
                                    onChange={handleUpdate}
                                    onRemove={handleRemove}
                                    onToggle={handleToggle}
                                    onSave={handleSave}
                                    isDirty={dirtyInstanceIds.has(inst.id)}
                                    isSaving={savingInstanceIds.has(inst.id)}
                                    saveStatus={saveStateByInstanceId[inst.id]?.status}
                                    saveMessage={saveStateByInstanceId[inst.id]?.message}
                                    errorMap={errorMapByInstanceId[inst.id] || {}}
                                />
                            );
                        })
                    )}
                </div>
            </div>

            <div className="p-4 bg-blue-50 border-l-4 border-blue-500 rounded-r-xl">
                <p className="text-sm text-blue-900">
                    <strong>Global Settings:</strong> Apply to all workers (max hours, rest periods, preferences)
                    <br />
                    <strong>Worker Rules:</strong> Apply to specific worker pairs (bans, pairings)
                </p>
            </div>

        </div>
    );
};

export default ConstraintsTab;
