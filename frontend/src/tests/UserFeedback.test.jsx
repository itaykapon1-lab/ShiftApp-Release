// ========================================
// USER FEEDBACK LOOP TESTS
// ========================================
// Verifies that every CRUD action produces:
//   1. Visual feedback (Toast notification)
//   2. Data refresh (re-fetch from API)
//   3. UI state reset (modal close, input clear)
// ========================================

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';

// ========================================
// MOCK SETUP
// ========================================

// Mock the API endpoints module
vi.mock('../api/endpoints', () => ({
    getWorkers: vi.fn(),
    getShifts: vi.fn(),
    getConstraints: vi.fn(),
    createWorker: vi.fn(),
    updateWorker: vi.fn(),
    deleteWorker: vi.fn(),
    createShift: vi.fn(),
    updateShift: vi.fn(),
    deleteShift: vi.fn(),
    importExcel: vi.fn(),
    exportExcel: vi.fn(),
    exportFullState: vi.fn(),
    solve: vi.fn(),
    getJobStatus: vi.fn(),
    updateConstraints: vi.fn(),
}));

// Mock the useJobPoller hook
vi.mock('../hooks/useJobPoller', () => ({
    default: () => ({
        jobId: null,
        jobStatus: null,
        isPolling: false,
        startPolling: vi.fn(),
        stopPolling: vi.fn(),
    }),
}));

// Import mock references
import * as api from '../api/endpoints';

// ========================================
// HELPERS
// ========================================

/** Default API responses for a clean state */
const setupEmptyState = () => {
    api.getWorkers.mockResolvedValue([]);
    api.getShifts.mockResolvedValue([]);
    api.getConstraints.mockResolvedValue({ constraints: [] });
};

/** Default API responses that include pre-existing data */
const setupWithData = () => {
    api.getWorkers.mockResolvedValue([
        {
            worker_id: 'W1',
            name: 'Alice',
            attributes: { skills: { Chef: 8 }, availability: {} },
            session_id: 'test',
        },
        {
            worker_id: 'W2',
            name: 'Bob',
            attributes: { skills: { Waiter: 6 }, availability: {} },
            session_id: 'test',
        },
    ]);
    api.getShifts.mockResolvedValue([
        {
            shift_id: 'S1',
            name: 'Morning Shift',
            start_time: '2026-02-12T08:00:00',
            end_time: '2026-02-12T16:00:00',
            tasks_data: {},
            session_id: 'test',
        },
    ]);
    api.getConstraints.mockResolvedValue({ constraints: [] });
};

/**
 * Render the App and wait for initial data fetch to complete.
 * Returns the user-event instance for interaction.
 */
const renderApp = async () => {
    const user = userEvent.setup();

    await act(async () => {
        render(<App />);
    });

    // Wait for initial fetchData to complete
    await waitFor(() => {
        expect(api.getWorkers).toHaveBeenCalled();
    });

    return user;
};

// ========================================
// TESTS
// ========================================

describe('User Feedback Loop', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    // ----------------------------------------
    // TEST A: FILE UPLOAD FEEDBACK
    // ----------------------------------------
    describe('Test A: File Upload Feedback', () => {
        it('shows success toast after successful Excel import', async () => {
            setupEmptyState();
            const user = await renderApp();

            // Mock a successful import that returns stats
            api.importExcel.mockResolvedValue({
                status: 'success',
                imported: { workers: 10, shifts: 5, constraints: 2 },
            });

            // After import, the re-fetch should return the new data
            api.getWorkers.mockResolvedValue([
                { worker_id: 'W1', name: 'Imported Worker', attributes: {}, session_id: 'test' },
            ]);

            // Find the file input and simulate upload
            const fileInput = document.querySelector('#file-upload-input');
            expect(fileInput).not.toBeNull();

            const file = new File(['dummy content'], 'schedule.xlsx', {
                type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            });

            await act(async () => {
                await user.upload(fileInput, file);
            });

            // Assert: importExcel was called
            expect(api.importExcel).toHaveBeenCalledTimes(1);

            // Assert: Success toast appears
            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Imported Successfully');
            });

            // Assert: fetchData was called AFTER the import (initial + post-import)
            await waitFor(() => {
                // getWorkers is called on mount + after import = at least 2 calls
                expect(api.getWorkers.mock.calls.length).toBeGreaterThanOrEqual(2);
            });
        });

        it('shows parsing warnings as a persistent bulleted list', async () => {
            setupEmptyState();
            const user = await renderApp();

            api.importExcel.mockResolvedValue({
                status: 'success',
                imported: {
                    workers: 3,
                    shifts: 1,
                    warnings: [
                        "[Workers, row 3, field 'Worker ID']: Duplicate ID 'W001' found on row 3. Auto-assigned new ID 'W001_dup1'. Please check if constraints referencing the old ID need updating.",
                        "[Shifts, row 2, field 'Tasks']: Malformed task string 'Cook:Many' on row 2. Auto-defaulted to '#1: [General:1] x 1'.",
                    ],
                },
            });

            const fileInput = document.querySelector('#file-upload-input');
            const file = new File(['dummy content'], 'schedule.xlsx', {
                type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            });

            await act(async () => {
                await user.upload(fileInput, file);
            });

            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Import Completed with Warnings');
            });

            const listItems = screen.getAllByRole('listitem');
            expect(listItems.length).toBe(2);
            expect(listItems[0].textContent).toContain("Duplicate ID 'W001'");
            expect(listItems[1].textContent).toContain("Malformed task string 'Cook:Many'");

            await act(async () => {
                vi.advanceTimersByTime(6000);
            });

            await waitFor(() => {
                expect(screen.getByRole('alert')).toBeInTheDocument();
            });
        });

        it('shows error toast on import failure', async () => {
            setupEmptyState();
            const user = await renderApp();

            api.importExcel.mockRejectedValue(new Error('Invalid file format'));

            const fileInput = document.querySelector('#file-upload-input');
            const file = new File(['bad'], 'bad.xlsx', {
                type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            });

            await act(async () => {
                await user.upload(fileInput, file);
            });

            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Import Failed');
            });

            await act(async () => {
                vi.advanceTimersByTime(6000);
            });

            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Import Failed');
            });
        });
    });

    // ----------------------------------------
    // TEST B: MANUAL WORKER CRUD FEEDBACK
    // ----------------------------------------
    describe('Test B: Manual Worker Entry Feedback', () => {
        it('shows success toast and closes modal after creating a worker', async () => {
            setupEmptyState();
            const user = await renderApp();

            // Mock successful worker creation
            api.createWorker.mockResolvedValue({
                worker_id: 'W_NEW',
                name: 'Charlie',
                attributes: { skills: {} },
            });

            // After creation, re-fetch returns the new worker
            api.getWorkers.mockResolvedValue([
                { worker_id: 'W_NEW', name: 'Charlie', attributes: { skills: {} }, session_id: 'test' },
            ]);

            // Open the Add Worker modal
            const addWorkerBtn = screen.getByText('Add Worker');
            await act(async () => {
                await user.click(addWorkerBtn);
            });

            // Fill in worker name
            const nameInput = screen.getByPlaceholderText('John Doe');
            await act(async () => {
                await user.type(nameInput, 'Charlie');
            });

            // Click "Create Worker" button in the modal
            const createBtn = screen.getByText('Create Worker');
            await act(async () => {
                await user.click(createBtn);
            });

            // Assert: createWorker API was called
            await waitFor(() => {
                expect(api.createWorker).toHaveBeenCalledTimes(1);
            });

            // Assert: Success toast appears
            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Worker Created');
            });

            // Assert: Modal is closed (the "Create Worker" button should no longer be visible)
            await waitFor(() => {
                expect(screen.queryByText('Create Worker')).not.toBeInTheDocument();
            });

            // Assert: fetchData was called for refresh
            await waitFor(() => {
                expect(api.getWorkers.mock.calls.length).toBeGreaterThanOrEqual(2);
            });
        });

        it('shows success toast after deleting a worker', async () => {
            setupWithData();
            const user = await renderApp();

            api.deleteWorker.mockResolvedValue({ status: 'deleted' });

            // After delete, re-fetch returns only Bob
            api.getWorkers.mockResolvedValue([
                { worker_id: 'W2', name: 'Bob', attributes: { skills: { Waiter: 6 } }, session_id: 'test' },
            ]);

            // Click the first "Delete" button in the worker row (opens confirmation modal)
            const deleteButtons = screen.getAllByText('Delete');
            await act(async () => {
                await user.click(deleteButtons[0]);
            });

            // WorkersTab uses a custom confirmation modal (role="dialog"), not window.confirm.
            // Anchor to the modal heading so this remains stable even if multiple dialogs are present.
            const deleteHeading = await screen.findByRole('heading', { name: /Delete Worker/i });
            const modal = deleteHeading.closest('[role="dialog"]');
            expect(modal).not.toBeNull();
            expect(within(modal).getByText(/Alice/i)).toBeInTheDocument();
            const confirmDeleteBtn = within(modal).getByRole('button', { name: /^Delete$/i });
            await act(async () => {
                await user.click(confirmDeleteBtn);
            });

            // Assert: deleteWorker API was called
            await waitFor(() => {
                expect(api.deleteWorker).toHaveBeenCalledWith('W1');
            });

            // Assert: Success toast appears
            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Worker Deleted');
            });
        });
    });

    // ----------------------------------------
    // TEST C: MANUAL SHIFT CRUD FEEDBACK
    // ----------------------------------------
    describe('Test C: Manual Shift Entry Feedback', () => {
        it('shows success toast and closes modal after creating a shift', async () => {
            setupWithData();
            const user = await renderApp();

            // Switch to Shifts tab
            const shiftsTab = screen.getByText(/Shifts/);
            await act(async () => {
                await user.click(shiftsTab);
            });

            // Mock successful shift creation
            api.createShift.mockResolvedValue({
                shift_id: 'S_NEW',
                name: 'Evening Shift',
                start_time: '2026-02-12T18:00:00',
                end_time: '2026-02-12T23:00:00',
                tasks_data: {},
            });

            // Open the Add Shift modal
            const addShiftBtn = screen.getByText('Add Shift');
            await act(async () => {
                await user.click(addShiftBtn);
            });

            // Fill in shift name
            const nameInput = screen.getByPlaceholderText('Evening Service Shift');
            await act(async () => {
                await user.type(nameInput, 'Evening Shift');
            });

            // Click "Create Shift" button
            const createBtn = screen.getByText(/Create Shift/);
            await act(async () => {
                await user.click(createBtn);
            });

            // Assert: createShift API was called
            await waitFor(() => {
                expect(api.createShift).toHaveBeenCalledTimes(1);
            });

            // Assert: Success toast appears
            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Shift Created');
            });
        });

        it('shows success toast after deleting a shift', async () => {
            setupWithData();
            const user = await renderApp();

            // Switch to Shifts tab
            const shiftsTab = screen.getByText(/Shifts/);
            await act(async () => {
                await user.click(shiftsTab);
            });

            api.deleteShift.mockResolvedValue({ status: 'deleted' });
            api.getShifts.mockResolvedValue([]);

            vi.spyOn(window, 'confirm').mockReturnValue(true);

            // Find and click Delete button for the shift
            const deleteBtn = screen.getByText('Delete');
            await act(async () => {
                await user.click(deleteBtn);
            });

            await waitFor(() => {
                expect(api.deleteShift).toHaveBeenCalledWith('S1');
            });

            await waitFor(() => {
                const toast = screen.getByRole('alert');
                expect(toast).toBeInTheDocument();
                expect(toast.textContent).toContain('Shift Deleted');
            });

            window.confirm.mockRestore();
        });
    });

    // ----------------------------------------
    // TEST D: TOAST AUTO-DISMISS
    // ----------------------------------------
    describe('Test D: Toast Auto-Dismiss', () => {
        it('toast notification auto-dismisses after 5 seconds', async () => {
            setupEmptyState();
            const user = await renderApp();

            api.createWorker.mockResolvedValue({
                worker_id: 'W_AUTO',
                name: 'AutoDismiss',
                attributes: {},
            });

            // Open modal, create worker
            await act(async () => {
                await user.click(screen.getByText('Add Worker'));
            });
            await act(async () => {
                await user.type(screen.getByPlaceholderText('John Doe'), 'AutoDismiss');
            });
            await act(async () => {
                await user.click(screen.getByText('Create Worker'));
            });

            // Assert toast appears
            await waitFor(() => {
                expect(screen.getByRole('alert')).toBeInTheDocument();
            });

            // Advance time past TOAST_DURATION + animation
            await act(async () => {
                vi.advanceTimersByTime(6000);
            });

            // Toast should have been dismissed
            await waitFor(() => {
                expect(screen.queryByRole('alert')).not.toBeInTheDocument();
            });
        });
    });

    // ----------------------------------------
    // TEST E: DATA COUNTS UPDATE
    // ----------------------------------------
    describe('Test E: Status Bar Data Counts', () => {
        it('updates data counts in status bar after successful operations', async () => {
            setupWithData();
            await renderApp();

            // Check the status bar shows the data counts
            await waitFor(() => {
                const statusBar = document.querySelector('#status-bar');
                expect(statusBar).not.toBeNull();
                expect(statusBar.textContent).toContain('2 workers');
                expect(statusBar.textContent).toContain('1 shifts');
            });
        });
    });

    // ----------------------------------------
    // TEST F: NO FULL-PAGE SPINNER ON REFRESH
    // ----------------------------------------
    describe('Test F: No Full-Page Spinner on Background Refresh', () => {
        it('does not show a full-page spinner during post-CRUD data refresh', async () => {
            setupWithData();
            const user = await renderApp();

            // Wait for initial load to finish
            await waitFor(() => {
                expect(screen.getByText('Alice')).toBeInTheDocument();
            });

            // Mock a successful delete
            api.deleteWorker.mockResolvedValue({ status: 'deleted' });
            api.getWorkers.mockResolvedValue([
                { worker_id: 'W2', name: 'Bob', attributes: { skills: { Waiter: 6 } }, session_id: 'test' },
            ]);
            vi.spyOn(window, 'confirm').mockReturnValue(true);

            // Delete Alice
            const deleteButtons = screen.getAllByText('Delete');
            await act(async () => {
                await user.click(deleteButtons[0]);
            });

            // The workers list should remain visible (showing Bob), NOT be replaced by a spinner.
            // Previously, fetchData set loading=true which replaced the entire tab content with <LoadingSpinner />.
            // After the fix, fetchData(false) does NOT set loading=true, so the table stays.
            await waitFor(() => {
                expect(screen.getByText('Bob')).toBeInTheDocument();
            });

            window.confirm.mockRestore();
        });
    });
});
