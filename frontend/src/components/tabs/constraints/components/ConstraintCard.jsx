/**
 * @module constraints/components/ConstraintCard
 * @description Single constraint card with strictness toggle, schema-driven fields,
 *   per-card save button with dirty/saving/saved state, and validation error display.
 */

import React, { useCallback } from 'react';
import { Trash2, RefreshCw, Save, CheckCircle2, AlertCircle } from 'lucide-react';
import { normalizeParamsForStrictness } from '../utils/constraintHelpers';
import SchemaFormField from './SchemaFormField';

/**
 * @param {Object} props
 * @param {Object} props.instance - Constraint instance data
 * @param {Object} props.schema - Constraint schema definition
 * @param {Object[]} props.workers - Available workers
 * @param {function} props.onChange - Callback when instance is updated
 * @param {function} props.onRemove - Callback when instance is removed
 * @param {function} props.onToggle - Callback when instance is toggled
 * @param {function} props.onSave - Callback when save is requested
 * @param {boolean} props.isDirty - Whether this instance has unsaved changes
 * @param {boolean} props.isSaving - Whether a save is in progress
 * @param {string} [props.saveStatus] - Current save status ('idle', 'success', 'error')
 * @param {string} [props.saveMessage] - Status message for save result
 * @param {Object} [props.errorMap={}] - Field-level validation errors
 */
const ConstraintCard = React.memo(({
    instance,
    schema,
    workers,
    onChange,
    onRemove,
    onToggle,
    onSave,
    isDirty,
    isSaving,
    saveStatus,
    saveMessage,
    errorMap = {},
}) => {
    const updateField = useCallback((fieldName, value) => {
        const nextParams = { ...instance.params, [fieldName]: value };
        onChange({ ...instance, params: nextParams });
    }, [instance, onChange]);

    const updateStrictness = useCallback((newType) => {
        const updated = {
            ...instance,
            type: newType,
            params: normalizeParamsForStrictness({
                params: instance.params,
                schema,
                nextType: newType,
            }),
        };
        onChange(updated);
    }, [instance, schema, onChange]);

    const workerAName = workers.find(w => w.worker_id === instance.params?.worker_a_id)?.name;
    const workerBName = workers.find(w => w.worker_id === instance.params?.worker_b_id)?.name;

    const displayName = instance.name ||
        (schema?.key === 'mutual_exclusion' && workerAName && workerBName
            ? `Ban: ${workerAName} - ${workerBName}`
            : schema?.key === 'colocation' && workerAName && workerBName
            ? `Pair: ${workerAName} + ${workerBName}`
            : schema?.label || instance.typeKey);

    const isHard = instance.type === 'HARD';

    return (
        <div className={`p-4 rounded-lg border-2 transition-all ${
            instance.enabled
                ? 'bg-white border-cyan-200 shadow-sm'
                : 'bg-gray-50 border-gray-200 opacity-60'
        }`}>
            <div className="flex justify-between items-start mb-3">
                <div className="flex items-center gap-3">
                    <input
                        type="checkbox"
                        checked={instance.enabled}
                        onChange={() => onToggle(instance.id)}
                        className="w-5 h-5 text-cyan-600 rounded"
                    />
                    <div>
                        <div className="flex items-center gap-2">
                            <select
                                value={instance.type || 'SOFT'}
                                onChange={(e) => updateStrictness(e.target.value)}
                                className={`px-2 py-0.5 rounded-lg text-xs font-bold border cursor-pointer ${
                                    isHard
                                        ? 'bg-red-100 text-red-800 border-red-300 hover:bg-red-200'
                                        : 'bg-yellow-100 text-yellow-800 border-yellow-300 hover:bg-yellow-200'
                                }`}
                                title="Constraint strictness"
                            >
                                <option value="HARD">HARD</option>
                                <option value="SOFT">SOFT</option>
                            </select>
                            <span className="font-bold text-gray-800">{displayName}</span>
                        </div>
                        {schema?.description && (
                            <p className="text-sm text-gray-500 mt-0.5">{schema.description}</p>
                        )}
                    </div>
                </div>
                <button
                    onClick={() => onRemove(instance.id)}
                    className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                    title="Remove constraint"
                >
                    <Trash2 className="w-4 h-4" />
                </button>
            </div>

            {schema && schema.fields && schema.fields.length > 0 && instance.enabled && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3 pt-3 border-t border-gray-100">
                    {schema.fields.map(field => {
                        if (['strictness', 'type', 'Strictness', 'Type'].includes(field.name)) {
                            return null;
                        }

                        const isPenaltyField = field.name === 'penalty';
                        const isDisabled = isPenaltyField && isHard;
                        const fieldLayoutClass = field.widget === 'checkbox' ? 'md:col-span-2' : '';

                        return (
                            <div
                                key={field.name}
                                className={`${fieldLayoutClass} ${isDisabled ? 'opacity-50' : ''}`.trim()}
                            >
                                <SchemaFormField
                                    field={field}
                                    value={isDisabled ? 0 : instance.params?.[field.name]}
                                    onChange={(val) => !isDisabled && updateField(field.name, val)}
                                    workers={workers}
                                    error={errorMap[field.name]}
                                />
                                {isPenaltyField && isHard && (
                                    <p className="text-xs text-gray-500 mt-1">
                                        Penalty disabled for HARD constraints
                                    </p>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between gap-3">
                <div className="min-h-[20px] text-sm">
                    {saveStatus === 'error' && (
                        <p className="text-red-600 flex items-center gap-1">
                            <AlertCircle className="w-4 h-4" />
                            {saveMessage || 'Failed to save constraint'}
                        </p>
                    )}
                    {saveStatus === 'success' && !isDirty && (
                        <p className="text-green-600 flex items-center gap-1">
                            <CheckCircle2 className="w-4 h-4" />
                            Saved
                        </p>
                    )}
                </div>

                <button
                    onClick={() => onSave(instance.id)}
                    disabled={!isDirty || isSaving}
                    className={`px-3 py-2 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2 ${
                        isDirty
                            ? 'bg-blue-600 text-white hover:bg-blue-700'
                            : 'bg-gray-200 text-gray-500 cursor-not-allowed'
                    } ${isSaving ? 'opacity-80' : ''}`}
                    title={isDirty ? 'Save this constraint' : 'No unsaved changes'}
                >
                    {isSaving ? (
                        <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : saveStatus === 'success' && !isDirty ? (
                        <CheckCircle2 className="w-4 h-4" />
                    ) : (
                        <Save className="w-4 h-4" />
                    )}
                    {isSaving ? 'Saving...' : (saveStatus === 'success' && !isDirty ? 'Saved' : 'Save Changes')}
                </button>
            </div>
        </div>
    );
});

ConstraintCard.displayName = 'ConstraintCard';

export default ConstraintCard;
