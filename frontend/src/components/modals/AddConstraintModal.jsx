import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Modal from '../common/Modal';
import SchemaFormField from '../tabs/constraints/components/SchemaFormField';
import {
    buildDefaultParamsFromSchema,
    getAllowedConstraintStrictness,
    isSoftOnlyConstraintType,
    normalizeConstraintKind,
    normalizeParamsForStrictness,
} from '../tabs/constraints/utils/constraintHelpers';
import { HelpPopover } from '../../help';

const STRICTNESS_OPTIONS = [
    { value: 'HARD', label: 'HARD' },
    { value: 'SOFT', label: 'SOFT' },
];

const createConstraintId = () => `ui_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

const isValueMissing = (field, value) => {
    if (!field?.required) return false;
    if (field.widget === 'checkbox') return false;
    if (field.widget === 'number') {
        return value === '' || value === undefined || value === null || Number.isNaN(Number(value));
    }
    return value === '' || value === undefined || value === null;
};

const AddConstraintModal = ({ isOpen, onClose, onAdd, schemas, workers = [] }) => {
    const [selectedType, setSelectedType] = useState('');
    const [selectedStrictness, setSelectedStrictness] = useState('SOFT');
    const [params, setParams] = useState({});
    const [submitAttempted, setSubmitAttempted] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState('');

    const resetForm = useCallback(() => {
        setSelectedType('');
        setSelectedStrictness('SOFT');
        setParams({});
        setSubmitAttempted(false);
        setIsSubmitting(false);
        setSubmitError('');
    }, []);

    useEffect(() => {
        if (isOpen) {
            resetForm();
        }
    }, [isOpen, resetForm]);

    const selectedSchema = useMemo(
        () => schemas.find((schema) => schema.key === selectedType),
        [schemas, selectedType]
    );

    const configFields = useMemo(
        () => (selectedSchema?.fields || []).filter(
            (field) => !['strictness', 'type', 'Strictness', 'Type'].includes(field.name)
        ),
        [selectedSchema]
    );
    const isSoftOnlyConstraint = isSoftOnlyConstraintType(selectedSchema?.key);

    const validationErrors = useMemo(() => {
        const nextErrors = {};
        configFields.forEach((field) => {
            if (isValueMissing(field, params[field.name])) {
                nextErrors[field.name] = `${field.label} is required`;
            }
        });
        return nextErrors;
    }, [configFields, params]);

    const displayStrictness = getAllowedConstraintStrictness(
        selectedSchema?.key,
        selectedStrictness,
        'SOFT'
    );
    const isHard = displayStrictness === 'HARD';

    const handleModalClose = useCallback(() => {
        resetForm();
        onClose();
    }, [onClose, resetForm]);

    const handleTypeChange = useCallback((value) => {
        setSelectedType(value);
        setSubmitAttempted(false);
        setSubmitError('');

        const schema = schemas.find((item) => item.key === value);
        if (!schema) {
            setSelectedStrictness('SOFT');
            setParams({});
            return;
        }

        const initialStrictness = getAllowedConstraintStrictness(
            schema.key,
            schema.constraint_type,
            'SOFT'
        );
        const defaultParams = buildDefaultParamsFromSchema(schema);

        setSelectedStrictness(initialStrictness);
        setParams(normalizeParamsForStrictness({
            params: defaultParams,
            schema,
            nextType: initialStrictness,
        }));
    }, [schemas]);

    const handleStrictnessChange = useCallback((value) => {
        const nextStrictness = getAllowedConstraintStrictness(
            selectedSchema?.key,
            value,
            'SOFT'
        );
        setSelectedStrictness(nextStrictness);
        setSubmitError('');

        if (!selectedSchema) return;

        setParams((prev) => normalizeParamsForStrictness({
            params: prev,
            schema: selectedSchema,
            nextType: nextStrictness,
        }));
    }, [selectedSchema]);

    const handleFieldChange = useCallback((fieldName, value) => {
        setSubmitError('');
        setParams((prev) => ({ ...prev, [fieldName]: value }));
    }, []);

    const handleSubmit = useCallback(async () => {
        setSubmitAttempted(true);
        if (!selectedSchema || Object.keys(validationErrors).length > 0) {
            return;
        }

        const strictness = getAllowedConstraintStrictness(
            selectedSchema.key,
            selectedStrictness,
            'SOFT'
        );
        const nextConstraint = {
            id: createConstraintId(),
            typeKey: selectedSchema.key,
            constraintKind: selectedSchema.constraint_kind,
            type: strictness,
            enabled: true,
            name: selectedSchema.label,
            description: selectedSchema.description,
            params: normalizeParamsForStrictness({
                params,
                schema: selectedSchema,
                nextType: strictness,
            }),
        };

        setIsSubmitting(true);
        setSubmitError('');

        try {
            const result = await onAdd(nextConstraint);
            if (result?.ok === false) {
                setSubmitError(result.message || 'Failed to save constraint');
                return;
            }
            handleModalClose();
        } catch (err) {
            setSubmitError(err?.message || 'Failed to save constraint');
        } finally {
            setIsSubmitting(false);
        }
    }, [handleModalClose, onAdd, params, selectedSchema, selectedStrictness, validationErrors]);

    const selectedScope = normalizeConstraintKind(selectedSchema?.constraint_kind);

    return (
        <Modal isOpen={isOpen} onClose={handleModalClose} title="Add Constraint" size="lg">
            <div className="space-y-6">
                <div className="flex flex-wrap items-center gap-2 text-xs text-cyan-900">
                    <span className="font-semibold">Strictness:</span>
                    <span>HARD / SOFT</span>
                    <HelpPopover hintId="hard_constraint" />
                    <HelpPopover hintId="soft_constraint" />
                    <span className="font-semibold sm:ml-2">Scope:</span>
                    <span>STATIC / DYNAMIC</span>
                    <HelpPopover hintId="static_constraint" />
                    <HelpPopover hintId="dynamic_constraint" />
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                        <label htmlFor="add-constraint-type" className="mb-2 block text-sm font-bold text-gray-700">
                            Constraint Type
                        </label>
                        <select
                            id="add-constraint-type"
                            value={selectedType}
                            onChange={(event) => handleTypeChange(event.target.value)}
                            aria-label="Constraint type"
                            disabled={isSubmitting}
                            className="w-full rounded-lg border-2 border-cyan-300 bg-white px-3 py-3 font-medium"
                        >
                            <option value="">Choose a constraint...</option>
                            {schemas.map((schema) => (
                                <option key={schema.key} value={schema.key}>
                                    {normalizeConstraintKind(schema.constraint_kind) === 'DYNAMIC' ? 'Dynamic: ' : 'Static: '}
                                    {schema.label}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div>
                        <label htmlFor="add-constraint-strictness" className="mb-2 block text-sm font-bold text-gray-700">
                            Strictness
                        </label>
                        <select
                            id="add-constraint-strictness"
                            value={displayStrictness}
                            onChange={(event) => handleStrictnessChange(event.target.value)}
                            aria-label="Constraint strictness"
                            disabled={!selectedSchema || isSubmitting || isSoftOnlyConstraint}
                            className="w-full rounded-lg border-2 border-cyan-300 bg-white px-3 py-3 font-medium disabled:cursor-not-allowed disabled:bg-gray-100"
                        >
                            {STRICTNESS_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                    {option.label}
                                </option>
                            ))}
                        </select>
                    </div>
                </div>

                {selectedSchema && isSoftOnlyConstraint && (
                    <p className="text-sm text-cyan-900">
                        Preferences are always soft constraints because they affect scoring, not feasibility.
                    </p>
                )}

                {selectedSchema ? (
                    <div className="rounded-xl border-2 border-cyan-200 bg-cyan-50 p-4">
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                            <div className="space-y-1">
                                <h3 className="text-base font-bold text-cyan-950">{selectedSchema.label}</h3>
                                {selectedSchema.description && (
                                    <p className="text-sm text-cyan-900">{selectedSchema.description}</p>
                                )}
                            </div>
                            <span className="inline-flex w-fit rounded-full bg-white px-3 py-1 text-xs font-bold text-cyan-900 ring-1 ring-cyan-200">
                                {selectedScope || 'CONFIGURABLE'}
                            </span>
                        </div>
                    </div>
                ) : (
                    <div className="rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500">
                        Choose a constraint type to configure its settings before adding it to the list.
                    </div>
                )}

                {selectedSchema && (
                    <div className="rounded-xl border-2 border-gray-200 bg-white p-4 sm:p-5">
                        <div className="mb-4">
                            <h3 className="text-base font-bold text-gray-800">Configuration</h3>
                            <p className="text-sm text-gray-500">Set the values that should be applied when this constraint is added.</p>
                        </div>

                        {configFields.length > 0 ? (
                            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                                {configFields.map((field) => {
                                    const isPenaltyField = field.name === 'penalty';
                                    const isDisabled = isPenaltyField && isHard;
                                    const fieldLayoutClass = field.widget === 'checkbox' ? 'sm:col-span-2' : '';

                                    return (
                                        <div
                                            key={field.name}
                                            className={`${fieldLayoutClass} ${isDisabled ? 'opacity-50' : ''}`.trim()}
                                        >
                                            <SchemaFormField
                                                field={field}
                                                value={isDisabled ? 0 : params[field.name]}
                                                onChange={(value) => !isDisabled && handleFieldChange(field.name, value)}
                                                workers={workers}
                                                error={submitAttempted ? validationErrors[field.name] : undefined}
                                                idPrefix="add-constraint"
                                            />
                                            {isPenaltyField && isHard && (
                                                <p className="mt-1 text-xs text-gray-500">
                                                    Penalty disabled for HARD constraints
                                                </p>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        ) : (
                            <p className="text-sm text-gray-500">This constraint uses its default configuration.</p>
                        )}
                    </div>
                )}

                {submitAttempted && !selectedSchema && (
                    <p className="text-sm font-medium text-red-600">Choose a constraint type before adding it.</p>
                )}

                {submitError && (
                    <p className="text-sm font-medium text-red-600">{submitError}</p>
                )}

                <div className="flex flex-col-reverse gap-3 border-t border-gray-200 pt-4 sm:flex-row sm:justify-end">
                    <button
                        type="button"
                        onClick={handleModalClose}
                        disabled={isSubmitting}
                        className="w-full rounded-lg border-2 border-gray-300 px-4 py-3 font-bold transition-colors hover:bg-gray-50 sm:w-auto"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={handleSubmit}
                        disabled={!selectedSchema || isSubmitting}
                        className="w-full rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-3 font-bold text-white shadow-md transition-all hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
                    >
                        {isSubmitting ? 'Saving Constraint...' : 'Add Constraint'}
                    </button>
                </div>
            </div>
        </Modal>
    );
};

export default AddConstraintModal;
