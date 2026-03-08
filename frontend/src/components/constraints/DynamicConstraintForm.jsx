// ========================================
// DynamicConstraintForm - Schema-driven field renderer
// Renders constraint fields from schema and emits clean params object
// ========================================

import React from 'react';
import { Trash2 } from 'lucide-react';

/**
 * @typedef {Object} UiFieldSchema
 * @property {string} name
 * @property {string} label
 * @property {'text'|'number'|'select'|'checkbox'} widget
 * @property {string} type
 * @property {boolean} required
 * @property {*} [default]
 * @property {string} [description]
 * @property {number} [minimum]
 * @property {number} [maximum]
 * @property {Array} [enum]
 * @property {number} order
 */

/**
 * @typedef {Object} ConstraintTypeSchema
 * @property {string} key
 * @property {string} label
 * @property {string} [description]
 * @property {string} constraint_type
 * @property {string} constraint_kind
 * @property {UiFieldSchema[]} fields
 */

/**
 * @typedef {Object} ConstraintInstance
 * @property {string} id
 * @property {string} typeKey
 * @property {Record<string, unknown>} params
 */

/**
 * @param {Object} props
 * @param {ConstraintTypeSchema} props.schema
 * @param {ConstraintInstance} props.instance
 * @param {function(ConstraintInstance): void} props.onChange
 * @param {function(): void} props.onRemove
 * @param {Record<string, string>} [props.errorMap]
 */
export const DynamicConstraintForm = ({
  schema,
  instance,
  onChange,
  onRemove,
  errorMap = {},
}) => {
  function updateField(field, rawValue) {
    let parsed = rawValue;
    if (field.type === 'integer' || field.type === 'number') {
      const num = Number(rawValue);
      parsed = Number.isNaN(num) ? undefined : num;
    }
    if (field.type === 'boolean') {
      parsed = Boolean(rawValue);
    }

    const nextParams = { ...instance.params, [field.name]: parsed };
    const nextInstance = { ...instance, params: nextParams };
    onChange(nextInstance);
  }

  return (
    <div className="p-4 rounded-lg border-2 border-cyan-200 bg-white shadow-sm">
      <div className="flex justify-between items-center mb-3">
        <strong className="text-gray-800">{schema.label}</strong>
        <button
          type="button"
          onClick={onRemove}
          className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
          aria-label="Remove constraint"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
      {schema.description && (
        <p className="text-sm text-gray-600 mb-3">{schema.description}</p>
      )}
      {errorMap.__category && (
        <div className="mb-3 text-sm text-red-600">
          {errorMap.__category}
        </div>
      )}

      <div className="space-y-3">
        {schema.fields.map((field) => {
          const value = instance.params[field.name] ?? '';
          const error = errorMap[field.name];
          const id = `${instance.id}-${field.name}`;

          return (
            <div key={field.name} className="space-y-1">
              <label htmlFor={id} className="block text-sm font-medium text-gray-700">
                {field.label}
              </label>

              {field.widget === 'number' && (
                <input
                  id={id}
                  type="number"
                  value={value}
                  onChange={(e) => updateField(field, e.target.value)}
                  min={field.minimum}
                  max={field.maximum}
                  step={field.type === 'integer' ? 1 : 'any'}
                  className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
                />
              )}

              {field.widget === 'text' && (
                <input
                  id={id}
                  type="text"
                  value={value}
                  onChange={(e) => updateField(field, e.target.value)}
                  className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
                />
              )}

              {field.widget === 'checkbox' && (
                <input
                  id={id}
                  type="checkbox"
                  checked={Boolean(value)}
                  onChange={(e) => updateField(field, e.target.checked)}
                  className="w-5 h-5 text-cyan-600 rounded border-gray-300"
                />
              )}

              {field.widget === 'select' && field.enum && (
                <select
                  id={id}
                  value={value}
                  onChange={(e) => updateField(field, e.target.value)}
                  className="w-full px-3 py-2 border-2 border-gray-200 rounded-lg focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
                >
                  {field.enum.map((opt) => (
                    <option key={String(opt)} value={String(opt)}>
                      {String(opt)}
                    </option>
                  ))}
                </select>
              )}

              {field.description && (
                <small className="block text-gray-500">{field.description}</small>
              )}
              {error && (
                <div className="text-red-600 text-sm">{error}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DynamicConstraintForm;
