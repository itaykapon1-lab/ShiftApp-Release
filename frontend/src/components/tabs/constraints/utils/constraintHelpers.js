/**
 * @module constraints/utils/constraintHelpers
 * @description Pure utility functions for constraint instance serialization,
 *   parameter normalization, and dirty-tracking snapshot management.
 *   Zero React dependencies — safe for use in tests and workers.
 */

export const DEFAULT_SOFT_PENALTY = -10;
export const STRESS_SEED = 20260215;

/**
 * Check whether a constraint schema defines a specific field.
 *
 * @param {Object} schema - Constraint schema definition
 * @param {string} fieldName - Field name to check for
 * @returns {boolean} True if the field exists in the schema
 */
export function schemaHasField(schema, fieldName) {
    if (!schema?.fields || !Array.isArray(schema.fields)) {
        return false;
    }
    return schema.fields.some((field) => field.name === fieldName);
}

/**
 * Normalize constraint parameters when switching between HARD and SOFT types.
 * HARD: penalty -> 0, strictness -> 'HARD'. SOFT: penalty -> DEFAULT_SOFT_PENALTY if invalid.
 *
 * @param {Object} options
 * @param {Object} options.params - Current parameter values
 * @param {Object} options.schema - Constraint schema definition
 * @param {string} options.nextType - Target type ('HARD' or 'SOFT')
 * @returns {Object} Normalized parameter object
 */
export function normalizeParamsForStrictness({ params, schema, nextType }) {
    const normalizedType = nextType === 'HARD' ? 'HARD' : 'SOFT';
    const nextParams = { ...(params || {}) };

    if (schemaHasField(schema, 'strictness')) {
        nextParams.strictness = normalizedType;
    }

    if (schemaHasField(schema, 'penalty')) {
        if (normalizedType === 'HARD') {
            nextParams.penalty = 0;
        } else {
            const penalty = nextParams.penalty;
            const isInvalidPenalty =
                penalty === undefined ||
                penalty === null ||
                Number.isNaN(Number(penalty)) ||
                Number(penalty) === 0;
            if (isInvalidPenalty) {
                nextParams.penalty = DEFAULT_SOFT_PENALTY;
            }
        }
    }

    Object.keys(nextParams).forEach((key) => {
        if (nextParams[key] === undefined) {
            delete nextParams[key];
        }
    });

    return nextParams;
}

/**
 * Create a seeded pseudo-random number generator (LCG).
 *
 * @param {number} seed - Integer seed value
 * @returns {function(): number} Function returning a float in [0, 1)
 */
export function createSeededRandom(seed) {
    let state = seed >>> 0;
    return () => {
        state = (1664525 * state + 1013904223) >>> 0;
        return state / 4294967296;
    };
}

/**
 * Pick a random element from an array using the given RNG.
 *
 * @param {Array} arr - Source array
 * @param {function(): number} rng - Random number generator
 * @returns {*|null} Random element or null if array is empty
 */
export function pickRandom(arr, rng) {
    if (!arr || arr.length === 0) return null;
    const idx = Math.floor(rng() * arr.length);
    return arr[idx];
}

/**
 * Build default parameter values from a constraint schema's field definitions.
 *
 * @param {Object} schema - Constraint schema definition
 * @returns {Object} Map of field name to default value
 */
export function buildDefaultParamsFromSchema(schema) {
    const defaultParams = {};
    (schema?.fields || []).forEach((field) => {
        if (field.default !== undefined) {
            defaultParams[field.name] = field.default;
        }
    });
    return defaultParams;
}

/**
 * Convert an API constraint object to a UI instance format.
 *
 * @param {Object} constraint - API constraint object
 * @param {number} idx - Index for generating a unique ID
 * @returns {Object} UI instance object with id, backendId, typeKey, params, etc.
 */
export function toInstance(constraint, idx) {
    const typeKey = constraint.category ?? constraint.typeKey ?? constraint.key;
    const constraintKind =
        constraint.constraint_kind ??
        constraint.constraintKind ??
        constraint.kind;

    return {
        id: `ui_${Date.now()}_${idx}_${Math.random().toString(36).slice(2, 9)}`,
        backendId: constraint.id,
        typeKey,
        constraintKind,
        params: constraint.params || {},
        enabled: constraint.enabled !== false,
        name: constraint.name,
        description: constraint.description,
        type: constraint.type,
    };
}

/**
 * Convert a UI instance back to API constraint format.
 *
 * @param {Object} inst - UI instance object
 * @returns {Object} API constraint object
 */
export function toApiConstraint(inst) {
    return {
        id: inst.backendId,
        category: inst.typeKey,
        type: inst.type || 'SOFT',
        enabled: inst.enabled !== false,
        name: inst.name,
        description: inst.description,
        params: inst.params,
    };
}

/**
 * Recursively sort object keys for deterministic JSON serialization.
 *
 * @param {*} value - Any value (objects get sorted, arrays recurse, primitives pass through)
 * @returns {*} A copy with all object keys sorted alphabetically
 */
export function sortDeep(value) {
    if (Array.isArray(value)) {
        return value.map(sortDeep);
    }
    if (value && typeof value === 'object') {
        const sorted = {};
        Object.keys(value).sort().forEach((key) => {
            sorted[key] = sortDeep(value[key]);
        });
        return sorted;
    }
    return value;
}

/**
 * Serialize a constraint instance to a deterministic JSON string for dirty tracking.
 *
 * @param {Object} inst - UI instance object
 * @returns {string} Deterministic JSON string
 */
export function serializeInstance(inst) {
    return JSON.stringify(sortDeep(toApiConstraint(inst)));
}

/**
 * Build a snapshot map from an array of instances for dirty tracking.
 *
 * @param {Object[]} instances - Array of UI instance objects
 * @returns {Object} Map of instance ID to serialized string
 */
export function buildSnapshotMap(instances) {
    const next = {};
    instances.forEach((inst) => {
        next[inst.id] = serializeInstance(inst);
    });
    return next;
}
