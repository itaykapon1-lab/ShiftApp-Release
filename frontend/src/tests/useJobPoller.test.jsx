import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useJobPoller } from '../hooks/useJobPoller';
import { getJobStatus } from '../api/endpoints';

vi.mock('../api/endpoints', () => ({
    getJobStatus: vi.fn(),
}));

const createDeferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
};

describe('useJobPoller', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.useFakeTimers();
        localStorage.clear();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('does not overlap polling requests when a request is still in flight', async () => {
        const firstResponse = createDeferred();
        getJobStatus.mockImplementationOnce(() => firstResponse.promise);
        getJobStatus.mockResolvedValue({ status: 'RUNNING' });

        const { result } = renderHook(() => useJobPoller(vi.fn(), vi.fn()));

        act(() => {
            result.current.startPolling('JOB_1');
        });

        act(() => {
            vi.advanceTimersByTime(2000);
        });
        expect(getJobStatus).toHaveBeenCalledTimes(1);

        act(() => {
            vi.advanceTimersByTime(10000);
        });
        expect(getJobStatus).toHaveBeenCalledTimes(1);

        await act(async () => {
            firstResponse.resolve({ status: 'RUNNING' });
            await Promise.resolve();
        });

        act(() => {
            vi.advanceTimersByTime(2000);
        });
        expect(getJobStatus).toHaveBeenCalledTimes(2);
    });

    it('does not invoke completion/failure callbacks after unmount', async () => {
        const delayedResponse = createDeferred();
        getJobStatus.mockImplementationOnce(() => delayedResponse.promise);

        const onComplete = vi.fn();
        const onFail = vi.fn();
        const { result, unmount } = renderHook(() => useJobPoller(onComplete, onFail));

        act(() => {
            result.current.startPolling('JOB_2');
        });

        act(() => {
            vi.advanceTimersByTime(2000);
        });
        expect(getJobStatus).toHaveBeenCalledTimes(1);

        unmount();

        await act(async () => {
            delayedResponse.resolve({ status: 'COMPLETED' });
            await Promise.resolve();
        });

        expect(onComplete).not.toHaveBeenCalled();
        expect(onFail).not.toHaveBeenCalled();
    });
});
