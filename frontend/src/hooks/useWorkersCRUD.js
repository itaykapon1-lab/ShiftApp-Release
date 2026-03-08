import { useState, useCallback } from 'react';
import * as api from '../api/endpoints';

/**
 * Custom hook encapsulating worker state and CRUD operations.
 *
 * @param {Object} deps
 * @param {React.MutableRefObject} deps.fetchDataRef - Ref to the fetchData function (avoids circular deps).
 * @param {Function} deps.showToast - Stable toast callback.
 * @returns Worker state and handler functions.
 */
export function useWorkersCRUD({ fetchDataRef, showToast }) {
  const [workers, setWorkers] = useState([]);
  const [isAddWorkerModalOpen, setIsAddWorkerModalOpen] = useState(false);
  const [editingWorker, setEditingWorker] = useState(null);

  const refreshData = useCallback(async () => {
    const fetchData = fetchDataRef.current;
    if (typeof fetchData !== 'function') {
      throw new Error('Data refresh bridge is not initialized');
    }
    await fetchData(false);
  }, [fetchDataRef]);

  const handleAddWorker = useCallback(async (payload, workerId = null) => {
    try {
      const isUpdate = !!workerId;
      const result = workerId
        ? await api.updateWorker(workerId, payload)
        : await api.createWorker(payload);

      // 1. VISUAL FEEDBACK: Success toast
      showToast(
        'success',
        isUpdate ? 'Worker Updated!' : 'Worker Created!',
        `"${payload.name}" has been ${isUpdate ? 'updated' : 'added'} successfully.`
      );

      // 2. DATA REFRESH: Re-fetch lists silently
      await refreshData();

      // 3. UI STATE RESET: Close modal & clear edit state
      setIsAddWorkerModalOpen(false);
      setEditingWorker(null);

      return result;
    } catch (err) {
      console.error('Worker operation failed:', err);
      showToast('error', 'Worker Operation Failed', err.message);
      throw err;
    }
  }, [refreshData, showToast]);

  const handleDeleteWorker = useCallback(async (workerId) => {
    try {
      await api.deleteWorker(workerId);

      // 1. VISUAL FEEDBACK
      showToast('success', 'Worker Deleted', 'The worker has been removed from the system.');

      // 2. DATA REFRESH
      await refreshData();
    } catch (err) {
      console.error('Delete worker failed:', err);
      showToast('error', 'Delete Failed', err.message);
      throw err;
    }
  }, [refreshData, showToast]);

  const openAddModal = useCallback(() => setIsAddWorkerModalOpen(true), []);
  const openEditModal = useCallback((worker) => {
    setEditingWorker(worker);
    setIsAddWorkerModalOpen(true);
  }, []);
  const closeModal = useCallback(() => {
    setIsAddWorkerModalOpen(false);
    setEditingWorker(null);
  }, []);

  return {
    workers, setWorkers,
    isAddWorkerModalOpen, editingWorker,
    handleAddWorker, handleDeleteWorker,
    openAddModal, openEditModal, closeModal,
  };
}
