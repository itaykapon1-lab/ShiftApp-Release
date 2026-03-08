// ========================================
// API ENDPOINTS - Specific API Calls
// ========================================

import apiClient from './client';

// Workers
export const getWorkers = () => apiClient('/workers');

export const createWorker = (worker) =>
    apiClient('/workers', {
        method: 'POST',
        body: JSON.stringify(worker),
    });

export const updateWorker = (id, worker) =>
    apiClient(`/workers/${id}`, {
        method: 'PUT',
        body: JSON.stringify(worker),
    });

export const deleteWorker = (id) =>
    apiClient(`/workers/${id}`, {
        method: 'DELETE',
    });

// Shifts
export const getShifts = () => apiClient('/shifts');

export const createShift = (shift) =>
    apiClient('/shifts', {
        method: 'POST',
        body: JSON.stringify(shift),
    });

export const updateShift = (id, shift) =>
    apiClient(`/shifts/${id}`, {
        method: 'PUT',
        body: JSON.stringify(shift),
    });

export const deleteShift = (id) =>
    apiClient(`/shifts/${id}`, {
        method: 'DELETE',
    });

// Constraints
export const getConstraints = () => apiClient('/constraints');

export const getConstraintSchema = () => apiClient('/constraints/schema');

export const updateConstraints = (constraints) =>
    apiClient('/constraints', {
        method: 'PUT',
        body: JSON.stringify({ constraints }),
    });

// File Operations
// Note: FormData is automatically detected by apiClient - no special headers needed
export const importExcel = (formData) =>
    apiClient('/files/import', {
        method: 'POST',
        body: formData,
    });

export const exportExcel = () =>
    apiClient('/files/export', {
        responseType: 'blob',
    });

export const exportFullState = () =>
    apiClient('/files/export-state', {
        responseType: 'blob',
    });

// Solver
export const solve = () =>
    apiClient('/solve', {
        method: 'POST',
    });

export const getJobStatus = (jobId) =>
    apiClient(`/status/${jobId}`);

export const runDiagnostics = (jobId) =>
    apiClient(`/solve/${jobId}/diagnose`, {
        method: 'POST',
    });

// Session Management
export const resetSessionData = () =>
    apiClient('/session/data', {
        method: 'DELETE',
    });
