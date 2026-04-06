/**
 * @module constraints/components/SchemaFormField
 * @description Schema-driven form field renderer. Given a field definition from
 *   the constraint schema, renders the appropriate input widget (worker_select,
 *   number, checkbox, select, or text).
 */

import React from 'react';
import WorkerSelect from './WorkerSelect';

/**
 * @param {Object} props
 * @param {Object} props.field - Schema field definition (name, label, widget, type, etc.)
 * @param {*} props.value - Current field value
 * @param {function} props.onChange - Callback when value changes
 * @param {Object[]} props.workers - Available workers (for worker_select widget)
 * @param {string} [props.error] - Validation error message
 * @param {string} [props.idPrefix='field'] - Optional prefix for generated input ids
 */
const SchemaFormField = React.memo(({ field, value, onChange, workers, error, idPrefix = 'field' }) => {
    const id = `${idPrefix}-${field.name}`;

    if (field.widget === 'worker_select') {
        return (
            <div className="space-y-1">
                <label htmlFor={id} className="block text-sm font-medium text-gray-700">
                    {field.label}
                </label>
                <WorkerSelect
                    id={id}
                    value={value || ''}
                    onChange={onChange}
                    workers={workers}
                    placeholder={`Select ${field.label.toLowerCase()}...`}
                />
                {field.description && (
                    <small className="block text-gray-500">{field.description}</small>
                )}
                {error && <div className="text-red-600 text-sm">{error}</div>}
            </div>
        );
    }

    if (field.widget === 'number') {
        return (
            <div className="space-y-1">
                <label htmlFor={id} className="block text-sm font-medium text-gray-700">
                    {field.label}
                </label>
                <input
                    id={id}
                    type="number"
                    value={value ?? ''}
                    onChange={(e) => {
                        const num = Number(e.target.value);
                        onChange(Number.isNaN(num) ? undefined : num);
                    }}
                    min={field.minimum}
                    max={field.maximum}
                    step={field.type === 'integer' ? 1 : 'any'}
                    className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:border-cyan-500"
                />
                {field.description && (
                    <small className="block text-gray-500">{field.description}</small>
                )}
                {error && <div className="text-red-600 text-sm">{error}</div>}
            </div>
        );
    }

    if (field.widget === 'checkbox') {
        return (
            <div className="space-y-1">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(e) => onChange(e.target.checked)}
                        className="w-5 h-5 text-cyan-600 rounded border-gray-300"
                    />
                    <span className="text-sm font-medium text-gray-700">{field.label}</span>
                </label>
                {field.description && (
                    <small className="block text-gray-500 ml-7">{field.description}</small>
                )}
                {error && <div className="text-red-600 text-sm">{error}</div>}
            </div>
        );
    }

    if (field.widget === 'select' && field.enum) {
        return (
            <div className="space-y-1">
                <label htmlFor={id} className="block text-sm font-medium text-gray-700">
                    {field.label}
                </label>
                <select
                    id={id}
                    value={value || ''}
                    onChange={(e) => onChange(e.target.value)}
                    className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:border-cyan-500"
                >
                    {field.enum.map((opt) => (
                        <option key={String(opt)} value={String(opt)}>
                            {String(opt)}
                        </option>
                    ))}
                </select>
                {field.description && (
                    <small className="block text-gray-500">{field.description}</small>
                )}
                {error && <div className="text-red-600 text-sm">{error}</div>}
            </div>
        );
    }

    return (
        <div className="space-y-1">
            <label htmlFor={id} className="block text-sm font-medium text-gray-700">
                {field.label}
            </label>
            <input
                id={id}
                type="text"
                value={value || ''}
                onChange={(e) => onChange(e.target.value)}
                className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:border-cyan-500"
            />
            {field.description && (
                <small className="block text-gray-500">{field.description}</small>
            )}
            {error && <div className="text-red-600 text-sm">{error}</div>}
        </div>
    );
});

SchemaFormField.displayName = 'SchemaFormField';

export default SchemaFormField;
