import { useState, useCallback, useRef } from 'react';
import * as api from '../api/endpoints';

/**
 * Custom hook encapsulating solver lifecycle: solve, reset, export, and job callbacks.
 *
 * @param {Object} deps
 * @param {Function} deps.showToast - Stable toast callback.
 * @param {Function} deps.setLoading - Setter for global loading state.
 * @param {React.MutableRefObject} deps.startPollingRef - Ref to startPolling from useJobPoller.
 * @param {React.MutableRefObject} deps.stopPollingRef - Ref to stopPolling from useJobPoller.
 * @param {Function} deps.resetAllState - Clears workers, shifts, constraints arrays.
 * @param {Function} deps.setStatus - Setter for the persistent status bar.
 * @param {Function} deps.getDataCounts - Returns { workers, shifts, constraints } counts for confirm dialog.
 * @returns Solver state and handler functions.
 */
export function useSolverLifecycle({
  showToast, setLoading, startPollingRef, stopPollingRef,
  resetAllState, setStatus, getDataCounts,
}) {
  const [solverResult, setSolverResult] = useState(null);
  const [isSolveStarting, setIsSolveStarting] = useState(false);
  const solveInFlightRef = useRef(false);

  const handleJobComplete = useCallback((result) => {
    setSolverResult(result);

    if (result.result_status === 'Optimal') {
      showToast('success', 'Optimization Complete!', 'Optimal schedule found. You can now export the results.');
    } else if (result.result_status === 'Feasible') {
      showToast('warning', 'Solution Found (Not Optimal)', 'A feasible schedule was found. Check diagnostics for details.');
    } else {
      showToast('success', 'Solver Completed', 'Review results in the diagnostics panel below.');
    }
    setLoading(false);
  }, [showToast, setLoading]);

  const handleJobFail = useCallback((result) => {
    setSolverResult(result);
    showToast('error', 'No Solution Found', 'The solver could not find a valid schedule. See diagnostics below.');
    setLoading(false);
  }, [showToast, setLoading]);

  const handleSolve = useCallback(async () => {
    if (solveInFlightRef.current) return;
    solveInFlightRef.current = true;
    setIsSolveStarting(true);

    try {
      showToast('info', 'Optimization Started', 'The solver is running in the background...');
      setLoading(true);

      const res = await api.solve();
      if (!res?.job_id) {
        throw new Error('Solver response missing job_id');
      }

      const startPolling = startPollingRef.current;
      if (typeof startPolling !== 'function') {
        throw new Error('Polling bridge is not initialized');
      }

      startPolling(res.job_id);
    } catch (err) {
      console.error('Solver Error:', err);
      showToast('error', 'Failed to Start Solver', err.message);
      setLoading(false);
    } finally {
      solveInFlightRef.current = false;
      setIsSolveStarting(false);
    }
  }, [showToast, setLoading, startPollingRef]);

  const handleResetSessionData = useCallback(async () => {
    const counts = getDataCounts();
    // Show confirmation dialog
    const confirmed = window.confirm(
      '\u26a0\ufe0f WARNING: This will permanently delete ALL data in this session:\n\n' +
      `\u2022 ${counts.workers} workers\n` +
      `\u2022 ${counts.shifts} shifts\n` +
      `\u2022 ${counts.constraints} constraints\n` +
      '\u2022 All solver results\n\n' +
      'This action cannot be undone. Continue?'
    );

    if (!confirmed) return;

    try {
      await api.resetSessionData();

      const stopPolling = stopPollingRef.current;
      if (typeof stopPolling === 'function') {
        stopPolling();
      }
      setLoading(false);

      // Clear all local state
      resetAllState();
      setSolverResult(null);

      showToast('success', 'Session Data Reset', 'All workers, shifts, and constraints have been deleted.');

      // Update status bar
      setStatus({
        type: 'info',
        message: 'Session cleared. Import an Excel file or add entries manually.'
      });
    } catch (err) {
      console.error('Reset Error:', err);
      showToast('error', 'Reset Failed', err.message);
    }
  }, [showToast, resetAllState, setStatus, getDataCounts, setLoading, stopPollingRef]);

  const handleExport = useCallback(async () => {
    try {
      const blob = await api.exportExcel();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `schedule_${new Date().toISOString().slice(0, 10)}.xlsx`;
      link.click();
      window.URL.revokeObjectURL(url);
      showToast('success', 'Schedule Exported!', 'The file has been downloaded.');
    } catch (err) {
      console.error('Export Error:', err);
      showToast('error', 'Export Failed', err.message);
    }
  }, [showToast]);

  const handleExportState = useCallback(async () => {
    try {
      const blob = await api.exportFullState();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `shiftapp_state_${new Date().toISOString().slice(0, 10)}.xlsx`;
      link.click();
      window.URL.revokeObjectURL(url);
      showToast('success', 'Full State Exported!', 'This file can be re-imported to restore the session.');
    } catch (err) {
      console.error('Export State Error:', err);
      showToast('error', 'Export Failed', err.message);
    }
  }, [showToast]);

  return {
    solverResult, setSolverResult,
    isSolveStarting,
    handleJobComplete, handleJobFail,
    handleSolve, handleResetSessionData,
    handleExport, handleExportState,
  };
}
