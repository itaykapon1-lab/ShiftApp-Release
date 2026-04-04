const normalizeToken = (value) => String(value ?? '').trim().toLowerCase();

const toFiniteNumber = (value, fallback = 0) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const trimTrailingPunctuation = (value) => String(value ?? '').trim().replace(/[.,;:!?]+$/, '');

const buildWorkerLookup = (assignments, workers) => {
    const idToName = new Map();
    const nameToId = new Map();

    const register = (workerId, workerName) => {
        const idKey = normalizeToken(workerId);
        const nameKey = normalizeToken(workerName);

        if (idKey && nameKey) {
            if (!idToName.has(idKey)) {
                idToName.set(idKey, nameKey);
            }
            if (!nameToId.has(nameKey)) {
                nameToId.set(nameKey, idKey);
            }
        }
    };

    workers.forEach((worker) => register(worker?.worker_id, worker?.name));
    assignments.forEach((assign) => register(assign?.worker_id, assign?.worker_name));

    return { idToName, nameToId };
};

const resolveWorkerTokens = (workerToken, workerLookup) => {
    const normalized = normalizeToken(workerToken);
    if (!normalized) {
        return new Set();
    }

    const tokens = new Set([normalized]);
    const mappedName = workerLookup.idToName.get(normalized);
    const mappedId = workerLookup.nameToId.get(normalized);

    if (mappedName) {
        tokens.add(mappedName);
    }
    if (mappedId) {
        tokens.add(mappedId);
    }

    return tokens;
};

const extractViolationHints = (description, metadata = {}) => {
    const text = String(description ?? '').trim();
    const safeMetadata = metadata && typeof metadata === 'object' ? metadata : {};

    const metadataWorkerTokens = [];
    if (Array.isArray(safeMetadata.worker_ids)) metadataWorkerTokens.push(...safeMetadata.worker_ids);
    if (Array.isArray(safeMetadata.worker_names)) metadataWorkerTokens.push(...safeMetadata.worker_names);
    ['primary_worker_id', 'primary_worker_name', 'paired_worker_id', 'paired_worker_name'].forEach((key) => {
        if (safeMetadata[key]) metadataWorkerTokens.push(safeMetadata[key]);
    });

    const metadataShiftIdHints = safeMetadata.shift_id ? [normalizeToken(safeMetadata.shift_id)] : [];
    const metadataShiftNameHint = safeMetadata.shift_name ? trimTrailingPunctuation(safeMetadata.shift_name) : '';

    const unwantedShiftMatch = text.match(/Worker\s+(.+?)\s+assigned to unwanted shift\s+(.+)$/i);
    if (unwantedShiftMatch) {
        return {
            workerToken: trimTrailingPunctuation(unwantedShiftMatch[1]),
            workerTokens: metadataWorkerTokens,
            shiftNameHint: trimTrailingPunctuation(unwantedShiftMatch[2]),
            shiftIdHints: metadataShiftIdHints,
        };
    }

    const restMatch = text.match(/Worker\s+(.+?)\s+has insufficient rest/i);
    const hoursMatch = text.match(/Worker\s+(.+?)\s+exceeded limit/i);
    const shiftPairMatch = text.match(/between shifts\s+([^\s]+)\s+and\s+([^\s.]+)\.?/i);
    const pairShiftMatch = text.match(/in shift\s+(.+?)\.?$/i);
    const pairWorkersTogetherMatch = text.match(
        /Worker\s+(.+?)\s+and\s+Worker\s+(.+?)\s+were assigned together in shift\s+(.+?)\.?$/i
    );
    if (pairWorkersTogetherMatch) {
        return {
            workerToken: '',
            workerTokens: [
                ...metadataWorkerTokens,
                trimTrailingPunctuation(pairWorkersTogetherMatch[1]),
                trimTrailingPunctuation(pairWorkersTogetherMatch[2]),
            ],
            shiftNameHint: trimTrailingPunctuation(pairWorkersTogetherMatch[3]) || metadataShiftNameHint,
            shiftIdHints: metadataShiftIdHints,
        };
    }

    const pairMissingMatch = text.match(
        /Worker\s+(.+?)\s+worked without required pair Worker\s+(.+?)\s+in shift\s+(.+?)\.?$/i
    );
    if (pairMissingMatch) {
        return {
            workerToken: trimTrailingPunctuation(pairMissingMatch[1]),
            workerTokens: [
                ...metadataWorkerTokens,
                trimTrailingPunctuation(pairMissingMatch[1]),
                trimTrailingPunctuation(pairMissingMatch[2]),
            ],
            shiftNameHint: trimTrailingPunctuation(pairMissingMatch[3]) || metadataShiftNameHint,
            shiftIdHints: metadataShiftIdHints,
        };
    }

    const shiftIdHints = shiftPairMatch
        ? [trimTrailingPunctuation(shiftPairMatch[1]), trimTrailingPunctuation(shiftPairMatch[2])]
            .map(normalizeToken)
            .filter(Boolean)
        : [];

    return {
        workerToken: restMatch ? trimTrailingPunctuation(restMatch[1]) : hoursMatch ? trimTrailingPunctuation(hoursMatch[1]) : '',
        workerTokens: metadataWorkerTokens,
        shiftNameHint: metadataShiftNameHint || (pairShiftMatch ? trimTrailingPunctuation(pairShiftMatch[1]) : ''),
        shiftIdHints: [...metadataShiftIdHints, ...shiftIdHints].filter(Boolean),
    };
};

export const mergeGlobalViolations = (assignments = [], penaltyBreakdown = {}, workers = []) => {
    const clonedAssignments = assignments.map((assign) => ({
        ...assign,
        global_violations: [],
        global_penalty_total: 0,
    }));

    if (!penaltyBreakdown || Object.keys(penaltyBreakdown).length === 0) {
        return clonedAssignments;
    }

    const workerLookup = buildWorkerLookup(clonedAssignments, workers);

    const findAssignmentIndexes = ({ workerTokens, shiftIdHints, shiftNameHint }) => {
        const normalizedShiftNameHint = normalizeToken(shiftNameHint);
        const directMatches = [];

        clonedAssignments.forEach((assign, idx) => {
            const assignWorkerId = normalizeToken(assign.worker_id);
            const assignWorkerName = normalizeToken(assign.worker_name);
            const assignShiftId = normalizeToken(assign.shift_id);
            const assignShiftName = normalizeToken(assign.shift_name);

            const workerMatch = workerTokens.size === 0
                ? true
                : workerTokens.has(assignWorkerId) || workerTokens.has(assignWorkerName);

            const hasShiftHints = shiftIdHints.length > 0 || Boolean(normalizedShiftNameHint);
            const shiftMatch = !hasShiftHints
                ? true
                : shiftIdHints.includes(assignShiftId)
                  || (normalizedShiftNameHint && normalizedShiftNameHint === assignShiftName);

            if (workerMatch && shiftMatch) {
                directMatches.push(idx);
            }
        });

        if (directMatches.length > 0) return directMatches;

        if (workerTokens.size > 0) {
            const workerFallback = [];
            clonedAssignments.forEach((assign, idx) => {
                const assignWorkerId = normalizeToken(assign.worker_id);
                const assignWorkerName = normalizeToken(assign.worker_name);
                if (workerTokens.has(assignWorkerId) || workerTokens.has(assignWorkerName)) {
                    workerFallback.push(idx);
                }
            });
            if (workerFallback.length > 0) return workerFallback;
        }

        if (shiftIdHints.length > 0 || normalizedShiftNameHint) {
            const shiftFallback = [];
            clonedAssignments.forEach((assign, idx) => {
                const assignShiftId = normalizeToken(assign.shift_id);
                const assignShiftName = normalizeToken(assign.shift_name);
                if (shiftIdHints.includes(assignShiftId) || (normalizedShiftNameHint && normalizedShiftNameHint === assignShiftName)) {
                    shiftFallback.push(idx);
                }
            });
            if (shiftFallback.length > 0) return shiftFallback;
        }

        return [];
    };

    Object.entries(penaltyBreakdown).forEach(([constraintName, data]) => {
        const violations = Array.isArray(data?.violations) ? data.violations : [];

        violations.forEach((rawViolation) => {
            const violation = typeof rawViolation === 'string'
                ? { description: rawViolation, penalty: data?.total_penalty }
                : (rawViolation || {});
            const description = String(violation.description || '').trim();
            if (!description) return;

            const hints = extractViolationHints(description, violation.metadata);
            const workerTokens = new Set();

            (Array.isArray(hints.workerTokens) ? hints.workerTokens : []).forEach((workerToken) => {
                resolveWorkerTokens(workerToken, workerLookup).forEach((token) => workerTokens.add(token));
            });
            resolveWorkerTokens(hints.workerToken, workerLookup).forEach((token) => workerTokens.add(token));

            const hasMatchingHints = workerTokens.size > 0
                || (Array.isArray(hints.shiftIdHints) && hints.shiftIdHints.length > 0)
                || Boolean(hints.shiftNameHint);
            if (!hasMatchingHints) return;

            const targetIndexes = findAssignmentIndexes({
                workerTokens,
                shiftIdHints: hints.shiftIdHints,
                shiftNameHint: hints.shiftNameHint,
            });
            if (targetIndexes.length === 0) return;

            const normalizedViolation = {
                constraint: constraintName,
                description,
                penalty: toFiniteNumber(violation.penalty, toFiniteNumber(data?.total_penalty, 0)),
                observed_value: violation.observed_value,
                limit_value: violation.limit_value,
                metadata: violation.metadata,
            };
            const violationDedupKey = `${constraintName}|${description}|${normalizedViolation.penalty}`;

            targetIndexes.forEach((idx) => {
                const assign = clonedAssignments[idx];
                const alreadyExists = assign.global_violations.some((item) => (
                    `${item.constraint}|${item.description}|${item.penalty}` === violationDedupKey
                ));
                if (!alreadyExists) {
                    assign.global_violations.push(normalizedViolation);
                }
            });
        });
    });

    clonedAssignments.forEach((assign) => {
        assign.global_penalty_total = assign.global_violations.reduce(
            (sum, violation) => sum + toFiniteNumber(violation?.penalty, 0),
            0
        );
    });

    return clonedAssignments;
};
