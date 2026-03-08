import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useWorkersCRUD } from '../hooks/useWorkersCRUD';
import { useShiftsCRUD } from '../hooks/useShiftsCRUD';
import { useSolverLifecycle } from '../hooks/useSolverLifecycle';
import * as api from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
    createWorker: vi.fn(),
    updateWorker: vi.fn(),
    deleteWorker: vi.fn(),
    createShift: vi.fn(),
    updateShift: vi.fn(),
    deleteShift: vi.fn(),
    solve: vi.fn(),
    resetSessionData: vi.fn(),
    exportExcel: vi.fn(),
    exportFullState: vi.fn(),
}));

describe('Ref Bridge Guards', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('worker CRUD fails safely when fetchData bridge is missing', async () => {
        api.createWorker.mockResolvedValue({ worker_id: 'W1' });
        const showToast = vi.fn();

        const { result } = renderHook(() =>
            useWorkersCRUD({ fetchDataRef: { current: null }, showToast })
        );

        await expect(
            result.current.handleAddWorker({
                name: 'Alice',
                attributes: { skills: {}, availability: {} },
            })
        ).rejects.toThrow('Data refresh bridge is not initialized');

        expect(showToast).toHaveBeenCalledWith(
            'error',
            'Worker Operation Failed',
            'Data refresh bridge is not initialized'
        );
    });

    it('shift CRUD fails safely when fetchData bridge is missing', async () => {
        api.createShift.mockResolvedValue({ shift_id: 'S1' });
        const showToast = vi.fn();

        const { result } = renderHook(() =>
            useShiftsCRUD({ fetchDataRef: { current: null }, showToast })
        );

        await expect(
            result.current.handleAddShift({
                name: 'Morning Shift',
                start_time: '2026-02-12T08:00:00',
                end_time: '2026-02-12T16:00:00',
                tasks_data: { tasks: [] },
            })
        ).rejects.toThrow('Data refresh bridge is not initialized');

        expect(showToast).toHaveBeenCalledWith(
            'error',
            'Shift Operation Failed',
            'Data refresh bridge is not initialized'
        );
    });

    it('solver lifecycle fails safely when polling bridge is missing', async () => {
        api.solve.mockResolvedValue({ job_id: 'JOB_1' });
        const showToast = vi.fn();
        const setLoading = vi.fn();

        const { result } = renderHook(() =>
            useSolverLifecycle({
                showToast,
                setLoading,
                startPollingRef: { current: null },
                stopPollingRef: { current: vi.fn() },
                resetAllState: vi.fn(),
                setStatus: vi.fn(),
                getDataCounts: () => ({ workers: 1, shifts: 1, constraints: 0 }),
            })
        );

        await act(async () => {
            await result.current.handleSolve();
        });

        expect(showToast).toHaveBeenCalledWith(
            'error',
            'Failed to Start Solver',
            'Polling bridge is not initialized'
        );
        expect(setLoading).toHaveBeenCalledWith(false);
    });
});
