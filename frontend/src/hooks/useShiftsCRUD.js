import { useState, useCallback } from 'react';
import * as api from '../api/endpoints';

/**
 * Custom hook encapsulating shift state and CRUD operations.
 *
 * @param {Object} deps
 * @param {React.MutableRefObject} deps.fetchDataRef - Ref to the fetchData function (avoids circular deps).
 * @param {Function} deps.showToast - Stable toast callback.
 * @returns Shift state and handler functions.
 */
export function useShiftsCRUD({ fetchDataRef, showToast }) {
  const [shifts, setShifts] = useState([]);
  const [isAddShiftModalOpen, setIsAddShiftModalOpen] = useState(false);
  const [editingShift, setEditingShift] = useState(null);

  const refreshData = useCallback(async () => {
    const fetchData = fetchDataRef.current;
    if (typeof fetchData !== 'function') {
      throw new Error('Data refresh bridge is not initialized');
    }
    await fetchData(false);
  }, [fetchDataRef]);

  const handleAddShift = useCallback(async (payload, shiftId = null) => {
    try {
      const isUpdate = !!shiftId;
      const result = shiftId
        ? await api.updateShift(shiftId, payload)
        : await api.createShift(payload);

      // 1. VISUAL FEEDBACK: Success toast
      showToast(
        'success',
        isUpdate ? 'Shift Updated!' : 'Shift Created!',
        `"${payload.name}" has been ${isUpdate ? 'updated' : 'added'} successfully.`
      );

      // 2. DATA REFRESH: Re-fetch lists silently
      await refreshData();

      // 3. UI STATE RESET: Close modal & clear edit state
      setIsAddShiftModalOpen(false);
      setEditingShift(null);

      return result;
    } catch (err) {
      console.error('Shift operation failed:', err);
      showToast('error', 'Shift Operation Failed', err.message);
      throw err;
    }
  }, [refreshData, showToast]);

  const handleDeleteShift = useCallback(async (shiftId) => {
    try {
      await api.deleteShift(shiftId);

      // 1. VISUAL FEEDBACK
      showToast('success', 'Shift Deleted', 'The shift has been removed from the system.');

      // 2. DATA REFRESH
      await refreshData();
    } catch (err) {
      console.error('Delete shift failed:', err);
      showToast('error', 'Delete Failed', err.message);
      throw err;
    }
  }, [refreshData, showToast]);

  const openAddModal = useCallback(() => setIsAddShiftModalOpen(true), []);
  const openEditModal = useCallback((shift) => {
    setEditingShift(shift);
    setIsAddShiftModalOpen(true);
  }, []);
  const closeModal = useCallback(() => {
    setIsAddShiftModalOpen(false);
    setEditingShift(null);
  }, []);

  return {
    shifts, setShifts,
    isAddShiftModalOpen, editingShift,
    handleAddShift, handleDeleteShift,
    openAddModal, openEditModal, closeModal,
  };
}
