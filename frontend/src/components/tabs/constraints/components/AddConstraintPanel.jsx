/**
 * @module constraints/components/AddConstraintPanel
 * @description Panel for adding new constraints. Provides a type selector,
 *   strictness selector, and Add button. Builds a new instance with default
 *   parameters from the selected schema.
 */

import React, { useState, useCallback } from 'react';
import { Plus } from 'lucide-react';
import {
    buildDefaultParamsFromSchema,
    normalizeConstraintKind,
    normalizeConstraintStrictness,
    normalizeParamsForStrictness,
} from '../utils/constraintHelpers';
import { HelpPopover } from '../../../../help';

/**
 * @param {Object} props
 * @param {Object[]} props.schemas - Available constraint schemas
 * @param {function} props.onAdd - Callback when a new constraint is added
 */
const AddConstraintPanel = React.memo(({ schemas, onAdd }) => {
    const [selectedType, setSelectedType] = useState('');
    const [selectedStrictness, setSelectedStrictness] = useState('SOFT');

    const handleTypeChange = useCallback((value) => {
        setSelectedType(value);
        const schema = schemas.find((s) => s.key === value);
        setSelectedStrictness(normalizeConstraintStrictness(schema?.constraint_type, 'SOFT'));
    }, [schemas]);

    const handleAdd = useCallback(() => {
        if (!selectedType) return;

        const schema = schemas.find(s => s.key === selectedType);
        if (!schema) return;

        const defaultParams = buildDefaultParamsFromSchema(schema);
        const strictness = selectedStrictness === 'HARD' ? 'HARD' : 'SOFT';

        const newConstraint = {
            id: `ui_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
            typeKey: selectedType,
            type: strictness,
            enabled: true,
            name: schema.label,
            description: schema.description,
            params: normalizeParamsForStrictness({
                params: defaultParams,
                schema,
                nextType: strictness,
            }),
        };

        onAdd(newConstraint);
        setSelectedType('');
        setSelectedStrictness('SOFT');
    }, [selectedType, selectedStrictness, schemas, onAdd]);

    return (
        <div className="bg-gradient-to-r from-cyan-50 to-blue-50 p-4 rounded-xl border-2 border-cyan-200">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-cyan-900">
                <span className="font-semibold">Strictness:</span>
                <span>HARD / SOFT</span>
                <HelpPopover hintId="hard_constraint" />
                <HelpPopover hintId="soft_constraint" />
                <span className="font-semibold ml-2">Scope:</span>
                <span>STATIC / DYNAMIC</span>
                <HelpPopover hintId="static_constraint" />
                <HelpPopover hintId="dynamic_constraint" />
            </div>
            <div className="flex items-center gap-3">
                <select
                    value={selectedType}
                    onChange={(e) => handleTypeChange(e.target.value)}
                    aria-label="Constraint type"
                    className="flex-1 px-3 py-2 border-2 border-cyan-300 rounded-lg font-medium bg-white"
                >
                    <option value="">Add a constraint...</option>
                    {schemas.map(s => (
                        <option key={s.key} value={s.key}>
                            {normalizeConstraintKind(s.constraint_kind) === 'DYNAMIC' ? 'Dynamic: ' : 'Static: '}
                            {s.label}
                        </option>
                    ))}
                </select>
                <select
                    value={selectedStrictness}
                    onChange={(e) => setSelectedStrictness(e.target.value)}
                    aria-label="Constraint strictness"
                    className="px-3 py-2 border-2 border-cyan-300 rounded-lg font-medium bg-white"
                >
                    <option value="HARD">HARD</option>
                    <option value="SOFT">SOFT</option>
                </select>
                <button
                    onClick={handleAdd}
                    disabled={!selectedType}
                    className="px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 text-white rounded-lg font-bold shadow-md hover:shadow-xl disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    <Plus className="w-4 h-4" />
                    Add
                </button>
            </div>
        </div>
    );
});

AddConstraintPanel.displayName = 'AddConstraintPanel';

export default AddConstraintPanel;
