const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const AUTO_GENERATED_TASK_NAME_PATTERN = /^task[_-][a-z0-9_-]+$/i;
const RANDOM_TOKEN_PATTERN = /^(?=.*[\d_-])[A-Za-z0-9_-]{12,}$/;

/**
 * Derive a short suffix from an ID for duplicate-name disambiguation.
 * Uses the last 4 characters of the last hyphen-delimited segment.
 */
export const shortIdSuffix = (entityId) => {
    if (!entityId) return '';
    const normalized = String(entityId).trim();
    if (!normalized) return '';
    const parts = normalized.split('-');
    const last = parts[parts.length - 1];
    return last.slice(-4);
};

const getEmployeeId = (employee) => {
    if (!employee || typeof employee !== 'object') return '';
    return employee.worker_id || employee.employee_id || employee.id || '';
};

const getEmployeeFullName = (employee) => {
    if (!employee || typeof employee !== 'object') return '';

    const directName = String(employee.name || employee.full_name || '').trim();
    if (directName) {
        return directName;
    }

    const composedName = [employee.first_name, employee.last_name]
        .map((part) => String(part || '').trim())
        .filter(Boolean)
        .join(' ')
        .trim();

    return composedName;
};

const buildDuplicateNameSet = (employeesList = []) => {
    const counts = new Map();

    employeesList.forEach((employee) => {
        const fullName = getEmployeeFullName(employee);
        if (!fullName) return;
        counts.set(fullName, (counts.get(fullName) || 0) + 1);
    });

    return new Set(
        [...counts.entries()]
            .filter(([, count]) => count > 1)
            .map(([fullName]) => fullName)
    );
};

/**
 * Maps an employee ID to a display name.
 * Duplicate names are disambiguated with the last 4 characters of the ID.
 */
export const formatEmployeeName = (employeeId, employeesList = []) => {
    const normalizedId = String(employeeId || '').trim();
    if (!normalizedId) return normalizedId;

    const employee = employeesList.find((candidate) => getEmployeeId(candidate) === normalizedId);
    if (!employee) {
        return normalizedId;
    }

    const fullName = getEmployeeFullName(employee);
    if (!fullName) {
        return normalizedId;
    }

    const duplicateNames = buildDuplicateNameSet(employeesList);
    if (!duplicateNames.has(fullName)) {
        return fullName;
    }

    const suffix = shortIdSuffix(normalizedId);
    return suffix ? `${fullName} (${suffix})` : fullName;
};

const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Replaces known employee IDs in diagnostic text with user-friendly names.
 */
export const formatDiagnosticMessage = (message, employeesList = []) => {
    if (typeof message !== 'string' || !message) {
        return message;
    }

    const replacements = employeesList
        .map((employee) => {
            const employeeId = getEmployeeId(employee);
            return employeeId
                ? [employeeId, formatEmployeeName(employeeId, employeesList)]
                : null;
        })
        .filter(Boolean)
        .sort(([leftId], [rightId]) => rightId.length - leftId.length);

    return replacements.reduce((formattedMessage, [employeeId, displayName]) => {
        const pattern = new RegExp(`(^|[^A-Za-z0-9])(${escapeRegExp(employeeId)})(?=$|[^A-Za-z0-9])`, 'g');
        return formattedMessage.replace(pattern, `$1${displayName}`);
    }, message);
};

/**
 * Detects placeholder-like task names that should not be shown to users.
 */
export const isMeaninglessTaskName = (taskName, taskId = '') => {
    const normalizedName = String(taskName || '').trim();
    const normalizedTaskId = String(taskId || '').trim();

    if (!normalizedName) {
        return true;
    }

    if (normalizedTaskId && normalizedName === normalizedTaskId) {
        return true;
    }

    return UUID_PATTERN.test(normalizedName)
        || AUTO_GENERATED_TASK_NAME_PATTERN.test(normalizedName)
        || RANDOM_TOKEN_PATTERN.test(normalizedName);
};

/**
 * Returns a user-friendly display label for a task without mutating task data.
 */
export const getDisplayTaskName = (taskOrName, index = 0) => {
    const taskName = typeof taskOrName === 'string' ? taskOrName : taskOrName?.name;
    const taskId = typeof taskOrName === 'string' ? '' : taskOrName?.task_id;
    const normalizedName = String(taskName || '').trim();

    if (isMeaninglessTaskName(normalizedName, taskId)) {
        return `Task Number: ${index + 1}`;
    }

    return normalizedName;
};
