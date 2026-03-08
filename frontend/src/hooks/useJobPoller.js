// ========================================
// JOB POLLER HOOK - Robust with Callbacks
// ========================================

import { useEffect, useState, useCallback } from 'react';
import { getJobStatus } from '../api/endpoints';
import { POLLING_INTERVAL_MS } from '../utils/constants';

const STORAGE_KEY = 'shiftapp_active_job_id';

/**
 * Custom hook for polling solver job status with localStorage persistence
 * If the user refreshes the page, the hook will resume polling the active job
 * 
 * @param {function} onJobComplete - Callback when job completes successfully
 * @param {function} onJobFail - Callback when job fails
 * @returns {object} { jobId, jobStatus, startPolling, stopPolling, isPolling }
 */
export const useJobPoller = (onJobComplete, onJobFail) => {
    const [jobId, setJobId] = useState(null);
    const [jobStatus, setJobStatus] = useState(null);
    const [isPolling, setIsPolling] = useState(false);

    // Restore active job from localStorage on mount
    useEffect(() => {
        const savedJobId = localStorage.getItem(STORAGE_KEY);
        if (savedJobId) {
            setJobId(savedJobId);
        }
    }, []);

    const stopPolling = useCallback(() => {
        setJobId(null);
        setJobStatus(null);
        setIsPolling(false);
        localStorage.removeItem(STORAGE_KEY);
    }, []);

    // Polling logic (guarded recursive timeout to avoid overlap and stale callbacks)
    useEffect(() => {
        if (!jobId) {
            setIsPolling(false);
            return;
        }

        setIsPolling(true);
        let disposed = false;
        let inFlight = false;
        let pollTimeout = null;

        const pollOnce = async () => {
            if (disposed || inFlight) return;
            inFlight = true;
            try {
                const statusRes = await getJobStatus(jobId);
                if (disposed) return;

                // Handle both uppercase and lowercase status
                const currentStatus = statusRes.status;
                const normalizedStatus = currentStatus ? currentStatus.toUpperCase() : 'UNKNOWN';

                // Update state with original status (preserve backend format)
                setJobStatus(currentStatus);

                // Define completion/failure statuses (all uppercase for comparison)
                const completedStatuses = ['COMPLETED', 'FINISHED', 'OPTIMAL'];
                const failedStatuses = ['FAILED', 'INFEASIBLE', 'ERROR'];

                if (completedStatuses.includes(normalizedStatus)) {
                    stopPolling();

                    if (onJobComplete) {
                        onJobComplete(statusRes);
                    }
                    return;
                } else if (failedStatuses.includes(normalizedStatus)) {
                    stopPolling();

                    if (onJobFail) {
                        onJobFail(statusRes);
                    }
                    return;
                }
                // RUNNING/PENDING: keep polling (no action needed)
                // Unknown status: keep polling as well
            } catch (err) {
                if (!disposed) {
                    console.error('Status polling error:', err);
                }
                // Don't stop polling on network errors, just log and retry
            } finally {
                inFlight = false;
            }

            if (!disposed) {
                pollTimeout = setTimeout(pollOnce, POLLING_INTERVAL_MS);
            }
        };

        pollTimeout = setTimeout(pollOnce, POLLING_INTERVAL_MS);

        // Cleanup: Stop interval when jobId changes or component unmounts
        return () => {
            disposed = true;
            if (pollTimeout) {
                clearTimeout(pollTimeout);
            }
        };
    }, [jobId, onJobComplete, onJobFail, stopPolling]);

    /**
     * Start polling a new job
     * @param {string} newJobId - Job ID to poll
     */
    const startPolling = useCallback((newJobId) => {
        setJobId(newJobId);
        setJobStatus('PENDING');
        localStorage.setItem(STORAGE_KEY, newJobId);
    }, []);

    return {
        jobId,
        jobStatus,
        isPolling,
        startPolling,
        stopPolling,
    };
};

export default useJobPoller;
