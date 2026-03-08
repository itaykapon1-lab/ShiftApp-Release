// ========================================
// Constraint Error Mapping Utility
// ========================================
//
// Maps backend validation errors (FastAPI/Pydantic-style) into
// a structure keyed by constraint instance ID and field name,
// so DynamicConstraintForm can highlight the exact fields.
//
// Expected backend error shape (per item in `detail` array):
//   {
//     loc: ["constraints", 0, "params", "max_hours"],
//     msg: "ensure this value is greater than or equal to 0",
//     type: "value_error.number.not_ge"
//   }
//
// The resulting structure:
//   {
//     "<instanceId>": {
//       "max_hours": "ensure this value is greater than or equal to 0"
//     }
//   }
//

/**
 * Build error map by instance ID and field name from backend errors.
 *
 * @param {Array<{id?: string, typeKey?: string, params?: Record<string, unknown>}>} instances
 *   The constraint instances in the same order they were sent to the backend.
 * @param {Array<{loc?: Array<string|number>, msg?: string}>} errors
 *   The raw error objects returned under `detail` from the backend.
 * @returns {Record<string, Record<string, string>>}
 *   Map: instanceId -> { fieldName -> message }
 */
export function buildErrorMap(instances, errors) {
  const result = {};

  if (!Array.isArray(instances) || !Array.isArray(errors)) {
    return result;
  }

  errors.forEach((err) => {
    const loc = Array.isArray(err?.loc) ? err.loc : [];
    const constraintsIdx = loc.indexOf('constraints');
    if (constraintsIdx === -1) return;

    const idx = loc[constraintsIdx + 1];
    if (typeof idx !== 'number') return;

    const instance = instances[idx];
    if (!instance || !instance.id) return;

    const nextLoc = loc.slice(constraintsIdx + 2);
    let fieldName = '__category';

    if (nextLoc[0] === 'params' && typeof nextLoc[1] === 'string') {
      fieldName = String(nextLoc[1]);
    }

    if (!result[instance.id]) {
      result[instance.id] = {};
    }

    // Only keep the first error message per field to avoid noise
    if (!result[instance.id][fieldName]) {
      result[instance.id][fieldName] = err.msg || 'Invalid value';
    }
  });

  return result;
}

export default buildErrorMap;

