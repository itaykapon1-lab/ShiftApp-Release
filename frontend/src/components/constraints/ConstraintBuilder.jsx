// ========================================
// ConstraintBuilder - Schema-driven constraint management
// Fetches schema, lets user add/remove constraints, uses DynamicConstraintForm
// ========================================

import React, { useEffect, useState } from 'react';
import { Shield, Plus } from 'lucide-react';
import DynamicConstraintForm from './DynamicConstraintForm';
import { getConstraintSchema } from '../../api/endpoints';

/**
 * Generate a unique ID for a constraint instance
 * @returns {string}
 */
function generateConstraintId() {
  return `constraint_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * @typedef {Object} ConstraintInstance
 * @property {string} id
 * @property {string} typeKey
 * @property {Record<string, unknown>} params
 */

/**
 * @param {Object} props
 * @param {ConstraintInstance[]} props.initialConstraints
 * @param {function(ConstraintInstance[]): void} props.onChange
 * @param {string} [props.className]
 * @param {Record<string, Record<string, string>>} [props.errorMapByInstanceId]
 *   Map of instanceId -> { fieldName -> errorMessage }
 */
export const ConstraintBuilder = ({
  initialConstraints = [],
  onChange,
  className = '',
  errorMapByInstanceId = {},
}) => {
  const [schemas, setSchemas] = useState([]);
  const [instances, setInstances] = useState(initialConstraints);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function loadSchema() {
      setLoading(true);
      setError(null);
      try {
        const data = await getConstraintSchema();
        setSchemas(Array.isArray(data) ? data : []);
      } catch (err) {
        console.error('Failed to load constraint schema:', err);
        setError(err.message);
        setSchemas([]);
      } finally {
        setLoading(false);
      }
    }
    loadSchema();
  }, []);

  // Sync instances when initialConstraints load from server (e.g. after parent fetch)
  useEffect(() => {
    if (!loading && initialConstraints && initialConstraints.length > 0) {
      setInstances(initialConstraints);
    }
  }, [loading, initialConstraints]);

  function handleAdd(typeKey) {
    const schema = schemas.find((s) => s.key === typeKey);
    if (!schema) return;

    const defaultParams = {};
    schema.fields.forEach((field) => {
      if (field.default !== undefined) {
        defaultParams[field.name] = field.default;
      }
    });

    const instance = {
      id: generateConstraintId(),
      typeKey,
      params: defaultParams,
    };

    const next = [...instances, instance];
    setInstances(next);
    onChange(next);
  }

  function handleUpdate(updated) {
    const next = instances.map((inst) =>
      inst.id === updated.id ? updated : inst
    );
    setInstances(next);
    onChange(next);
  }

  function handleRemove(id) {
    const next = instances.filter((inst) => inst.id !== id);
    setInstances(next);
    onChange(next);
  }

  if (loading) {
    return (
      <div className={`p-6 rounded-xl border-2 border-cyan-200 bg-cyan-50 ${className}`}>
        <p className="text-cyan-800">Loading constraint schema...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`p-6 rounded-xl border-2 border-red-200 bg-red-50 ${className}`}>
        <p className="text-red-800">
          Failed to load constraint schema: {error}
        </p>
      </div>
    );
  }

  if (schemas.length === 0) {
    return (
      <div className={`p-6 rounded-xl border-2 border-gray-200 bg-gray-50 ${className}`}>
        <p className="text-gray-600">No constraint types available.</p>
      </div>
    );
  }

  return (
    <div className={`bg-gradient-to-r from-cyan-50 to-blue-50 p-6 rounded-xl border-2 border-cyan-300 shadow-lg ${className}`}>
      <h3 className="text-lg font-bold text-cyan-900 mb-4 flex items-center gap-2">
        <Shield className="w-5 h-5" />
        Schema-Driven Constraint Builder
      </h3>

      <div className="mb-4">
        <label className="block text-sm font-bold text-gray-700 mb-2">
          Add constraint
        </label>
        <select
          defaultValue=""
          onChange={(e) => {
            const val = e.target.value;
            if (val) handleAdd(val);
          }}
          className="w-full max-w-md px-3 py-2 border-2 border-cyan-300 rounded-lg font-medium bg-white"
        >
          <option value="">Select type...</option>
          {schemas.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-3">
        {instances.map((inst) => {
          const schema = schemas.find((s) => s.key === inst.typeKey);
          if (!schema) return null;
          const instanceErrorMap = errorMapByInstanceId?.[inst.id] || {};

          return (
            <DynamicConstraintForm
              key={inst.id}
              schema={schema}
              instance={inst}
              onChange={handleUpdate}
              onRemove={() => handleRemove(inst.id)}
              errorMap={instanceErrorMap}
            />
          );
        })}
      </div>
    </div>
  );
};

export default ConstraintBuilder;
