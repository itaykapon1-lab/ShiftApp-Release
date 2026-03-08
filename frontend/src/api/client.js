// ========================================
// API CLIENT - Centralized Fetch Wrapper
// ========================================

// Use environment variable for deployability, fallback to localhost for development
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api/v1';

/**
 * Centralized fetch wrapper with error handling.
 *
 * CRITICAL: This client ensures session cookies are sent with every request
 * via `credentials: 'include'`. Without this, the backend treats each
 * request as a new session, causing "ghost data" issues.
 *
 * @param {string} endpoint - API endpoint path
 * @param {object} options - Fetch options (method, headers, body, etc.)
 * @returns {Promise} - Response data
 */
export const apiClient = async (endpoint, options = {}) => {
    const url = `${API_BASE}${endpoint}`;

    // Determine if this is a FormData request (file upload)
    const isFormData = options.body instanceof FormData;

    // Build headers:
    // - For FormData: Don't set Content-Type (browser sets it with boundary)
    // - For JSON: Set Content-Type: application/json
    const headers = {};
    if (!isFormData) {
        headers['Content-Type'] = 'application/json';
    }
    // Merge any custom headers (but skip if empty object passed for FormData)
    if (options.headers && Object.keys(options.headers).length > 0) {
        Object.assign(headers, options.headers);
    }

    try {
        const response = await fetch(url, {
            // CRITICAL: Always include credentials to send session cookies
            // Without this, each request creates a new session (data isolation failure)
            credentials: 'include',
            ...options,
            headers, // Override headers after spreading options
        });

        // Handle non-JSON responses (like blob for Excel export)
        if (options.responseType === 'blob') {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            return await response.blob();
        }

        // Parse JSON response (may fail for empty bodies)
        let data = null;
        try {
            data = await response.json();
        } catch {
            data = null;
        }

        // Handle error responses (422, 400, etc.)
        if (!response.ok) {
            const detail = data && typeof data === 'object' ? data.detail : undefined;
            const message =
                (Array.isArray(detail) ? undefined : detail) ||
                data?.message ||
                `HTTP ${response.status}: ${response.statusText}`;

            const error = new Error(message);
            // Attach extra metadata so callers (like ConstraintsTab) can inspect validation details
            error.status = response.status;
            error.data = data;
            throw error;
        }

        return data;
    } catch (error) {
        // Re-throw with additional context
        console.error(`❌ API Error [${options.method || 'GET'} ${endpoint}]:`, error);
        throw error;
    }
};

export default apiClient;
