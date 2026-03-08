// ========================================
// MAIN APP - Clean & Modular
// Feedback Loop Fix: All CRUD actions now
// trigger Toast + Data Refresh + UI Reset
// ========================================

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Upload, Download, Play, RefreshCw, AlertCircle, CheckCircle, Clock, X, Info, Trash2 } from 'lucide-react';

// API
import * as api from './api/endpoints';

// Hooks
import useJobPoller from './hooks/useJobPoller';
import { useWorkersCRUD } from './hooks/useWorkersCRUD';
import { useShiftsCRUD } from './hooks/useShiftsCRUD';
import { useSolverLifecycle } from './hooks/useSolverLifecycle';

// Components
import LoadingSpinner from './components/common/LoadingSpinner';
import WorkersTab from './components/tabs/WorkersTab';
import ShiftsTab from './components/tabs/ShiftsTab';
import ConstraintsTab from './components/tabs/constraints';
import AddWorkerModal from './components/modals/AddWorkerModal';
import AddShiftModal from './components/modals/AddShiftModal';
import SolverDiagnostics from './components/SolverDiagnostics';
import ScheduleTab from './components/tabs/ScheduleTab';
import { HelpButton } from './help';

import ToastNotification from './components/common/ToastNotification';


// ========================================
// MAIN APP
// ========================================

function App() {
  // ── Global UI state (stays in App) ──
  const [activeTab, setActiveTab] = useState('workers');
  const [constraints, setConstraints] = useState([]);
  const [loading, setLoading] = useState(false);           // Full-page loading (initial only)
  const [isRefreshing, setIsRefreshing] = useState(false); // Background refresh (no spinner)
  const [toast, setToast] = useState(null);
  const [status, setStatus] = useState(null);

  // ── Refs ──
  const fileInputRef = useRef(null);
  const fetchDataRef = useRef(null);
  const startPollingRef = useRef(null);
  const stopPollingRef = useRef(null);

  // ── Toast helpers (stable — [] deps) ──
  const showToast = useCallback((type, message, detail = null, options = {}) => {
    setToast({
      type,
      message,
      detail,
      persist: Boolean(options.persist),
      details: Array.isArray(options.details) ? options.details : null,
      category: options.category || null,
      key: Date.now()
    });
  }, []);

  const dismissToast = useCallback(() => {
    setToast(null);
  }, []);

  const formatImportIssue = useCallback((issue) => {
    if (!issue) return null;
    if (typeof issue === 'string') return issue;

    const locationParts = [];
    if (issue.sheet) locationParts.push(issue.sheet);
    if (issue.row !== undefined && issue.row !== null) locationParts.push(`row ${issue.row}`);
    if (issue.field) locationParts.push(`field '${issue.field}'`);

    const message = issue.message || JSON.stringify(issue);
    if (locationParts.length === 0) {
      return message;
    }

    return `[${locationParts.join(', ')}]: ${message}`;
  }, []);

  // ── Domain hooks ──
  const workersCRUD = useWorkersCRUD({ fetchDataRef, showToast });
  const shiftsCRUD = useShiftsCRUD({ fetchDataRef, showToast });

  // Cross-hook callbacks for solver lifecycle
  const resetAllState = useCallback(() => {
    workersCRUD.setWorkers([]);
    shiftsCRUD.setShifts([]);
    setConstraints([]);
  }, [workersCRUD.setWorkers, shiftsCRUD.setShifts]);

  const getDataCounts = useCallback(() => ({
    workers: workersCRUD.workers.length,
    shifts: shiftsCRUD.shifts.length,
    constraints: constraints.length,
  }), [workersCRUD.workers.length, shiftsCRUD.shifts.length, constraints.length]);

  const solver = useSolverLifecycle({
    showToast, setLoading, startPollingRef, stopPollingRef,
    resetAllState, setStatus, getDataCounts,
  });

  // ── Job polling (receives callbacks from solver hook) ──
  const { jobId, jobStatus, isPolling, startPolling, stopPolling } = useJobPoller(
    solver.handleJobComplete,
    solver.handleJobFail
  );

  // Wire startPollingRef after useJobPoller initializes
  startPollingRef.current = startPolling;
  stopPollingRef.current = stopPolling;

  // ── Central data fetch (closes over setters from hooks) ──
  const fetchData = async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
    setIsRefreshing(true);

    try {
      const [workersData, shiftsData, constraintsData] = await Promise.all([
        api.getWorkers(),
        api.getShifts(),
        api.getConstraints()
      ]);

      const workersArray = Array.isArray(workersData) ? workersData : (workersData?.data || []);
      const shiftsArray = Array.isArray(shiftsData) ? shiftsData : (shiftsData?.data || []);
      const constraintsArray = constraintsData?.constraints || [];

      workersCRUD.setWorkers(workersArray);
      shiftsCRUD.setShifts(shiftsArray);
      setConstraints(constraintsArray);

      // Update status bar with data counts (persistent info, not a toast)
      if (workersArray.length > 0 || shiftsArray.length > 0) {
        setStatus({
          type: 'success',
          message: `${workersArray.length} workers \u00b7 ${shiftsArray.length} shifts \u00b7 ${constraintsArray.length} constraints loaded`
        });
      } else {
        setStatus({
          type: 'info',
          message: 'No data found. Import an Excel file or add entries manually.'
        });
      }
    } catch (err) {
      console.error('Fetch Error:', err);
      showToast('error', 'Failed to fetch data', err.message);
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  };

  // Wire fetchDataRef after fetchData is defined
  fetchDataRef.current = fetchData;

  // Initial Data Fetch
  useEffect(() => {
    const fetchInitialData = fetchDataRef.current;
    if (typeof fetchInitialData === 'function') {
      fetchInitialData(true);
    }
  }, []);

  // ── File upload (stays in App — tied to fileInputRef DOM element) ──
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    // Show immediate "uploading" feedback
    showToast('info', `Importing "${file.name}"...`, 'Please wait while the file is processed.');

    try {
      const formData = new FormData();
      formData.append('file', file);
      const result = await api.importExcel(formData);

      // Extract import stats for a rich toast message
      const stats = result?.imported || {};
      const importedDetail = [
        stats.workers != null && `${stats.workers} workers`,
        stats.shifts != null && `${stats.shifts} shifts`,
      ].filter(Boolean).join(', ');

      const warnings = Array.isArray(stats.warnings)
        ? stats.warnings.map(formatImportIssue).filter(Boolean)
        : [];

      if (warnings.length === 0) {
        // Clean import — green success toast
        showToast(
          'success',
          'Excel Imported Successfully!',
          importedDetail || 'Data has been loaded into the system.'
        );
      } else {
        // Import succeeded but has non-fatal issues — amber warning toast.
        const header = importedDetail
          ? `Imported ${importedDetail} \u2014 please review the issue${warnings.length > 1 ? 's' : ''} below:`
          : `Import completed with ${warnings.length} warning${warnings.length > 1 ? 's' : ''}:`;
        showToast('warning', 'Import Completed with Warnings', header, {
          persist: true,
          category: 'parsing',
          details: warnings,
        });
      }

      // Refresh data silently (no spinner — user already sees the toast)
      await fetchData(false);
    } catch (err) {
      console.error('Import Error:', err);
      const detailPayload = err?.data?.detail;
      const validationErrors = detailPayload?.validation_errors?.errors || [];
      const validationWarnings = detailPayload?.validation_errors?.warnings || [];
      const issueList = [...validationErrors, ...validationWarnings]
        .map(formatImportIssue)
        .filter(Boolean);
      const detailMessage = detailPayload?.summary || detailPayload?.message || err.message;

      showToast('error', 'Import Failed', detailMessage, {
        persist: true,
        category: 'parsing',
        details: issueList.length > 0 ? issueList : null,
      });
    } finally {
      // CRITICAL: Reset the file input so the same file can be re-imported
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  // ========================================
  // RENDER
  // ========================================

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 via-blue-50 to-purple-50">
      {/* Toast Notification (floating top-right) */}
      <ToastNotification toast={toast} onDismiss={dismissToast} />

      {/* Header */}
      <header className="bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 text-white shadow-2xl">
        <div className="container mx-auto px-6 py-5 flex justify-between items-center">
          <div className="flex items-center gap-3">
            <RefreshCw className={`w-7 h-7 ${isRefreshing ? 'animate-spin' : ''}`} />
            <div>
              <h1 className="text-3xl font-black tracking-tight">Shift Optimizer Pro</h1>
              <p className="text-xs text-purple-200">Advanced Scheduling System</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {isPolling && (
              <div className="flex items-center px-5 py-2 bg-white bg-opacity-20 rounded-full backdrop-blur-sm shadow-lg">
                <Clock className="w-5 h-5 mr-2 animate-spin" />
                <span className="font-bold">{jobStatus || 'PROCESSING'}</span>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="container mx-auto px-6 py-8">
        {/* Persistent Info Bar (data counts — not a toast) */}
        {status && (
          <div id="status-bar" className={`mb-6 px-5 py-3 rounded-xl flex items-center gap-3 text-sm font-medium transition-all ${status.type === 'info'
            ? 'bg-blue-50 border border-blue-200 text-blue-700'
            : 'bg-emerald-50 border border-emerald-200 text-emerald-700'
            }`}>
            {status.type === 'info'
              ? <Info className="w-4 h-4 flex-shrink-0" />
              : <CheckCircle className="w-4 h-4 flex-shrink-0" />
            }
            <span>{status.message}</span>
            {isRefreshing && (
              <RefreshCw className="w-4 h-4 ml-auto animate-spin text-gray-400" />
            )}
          </div>
        )}

        {/* Action Bar */}
        <div className="bg-white p-6 rounded-2xl shadow-2xl mb-8 border-2 border-gray-200">
          <div className="flex flex-wrap gap-4 justify-between items-center">
            <div className="flex gap-3 flex-wrap">
              <label className="flex items-center px-5 py-3 bg-gradient-to-r from-indigo-100 to-purple-100 border-3 border-indigo-300 rounded-xl cursor-pointer hover:from-indigo-200 hover:to-purple-200 transition-all font-bold text-indigo-800 shadow-md hover:shadow-lg">
                <Upload className="w-5 h-5 mr-2" />
                Import Excel
                <input
                  ref={fileInputRef}
                  id="file-upload-input"
                  type="file"
                  className="hidden"
                  accept=".xlsx,.xls"
                  onChange={handleFileUpload}
                />
              </label>
              <button
                id="btn-export-result"
                onClick={solver.handleExport}
                disabled={shiftsCRUD.shifts.length === 0}
                className="flex items-center px-5 py-3 bg-gradient-to-r from-green-100 to-emerald-100 border-3 border-green-300 rounded-xl hover:from-green-200 hover:to-emerald-200 transition-all font-bold text-green-800 shadow-md hover:shadow-lg disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Download className="w-5 h-5 mr-2" />
                Export Result
              </button>
              <button
                id="btn-export-state"
                onClick={solver.handleExportState}
                disabled={workersCRUD.workers.length === 0 && shiftsCRUD.shifts.length === 0}
                className="flex items-center px-5 py-3 bg-gradient-to-r from-blue-100 to-cyan-100 border-3 border-blue-300 rounded-xl hover:from-blue-200 hover:to-cyan-200 transition-all font-bold text-blue-800 shadow-md hover:shadow-lg disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Download className="w-5 h-5 mr-2" />
                Export State
              </button>
              <HelpButton topicId="data.management" label="Data Help" variant="neutral" />
            </div>
            <div className="flex items-center gap-3">
              <button
                id="btn-reset-data"
                onClick={solver.handleResetSessionData}
                disabled={workersCRUD.workers.length === 0 && shiftsCRUD.shifts.length === 0}
                className="flex items-center px-4 py-3 bg-gradient-to-r from-red-100 to-rose-100 border-3 border-red-300 rounded-xl hover:from-red-200 hover:to-rose-200 transition-all font-bold text-red-800 shadow-md hover:shadow-lg disabled:opacity-40 disabled:cursor-not-allowed"
                title="Delete all session data"
              >
                <Trash2 className="w-5 h-5 mr-2" />
                Reset Data
              </button>
              <button
                id="btn-run-solver"
                onClick={solver.handleSolve}
                disabled={isPolling || solver.isSolveStarting || workersCRUD.workers.length === 0}
                className={`flex items-center px-8 py-3 rounded-xl text-white font-black text-lg shadow-2xl transition-all hover:scale-105 ${(isPolling || solver.isSolveStarting || workersCRUD.workers.length === 0)
                  ? 'bg-gray-400 cursor-not-allowed hover:scale-100'
                  : 'bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 hover:from-indigo-700 hover:via-purple-700 hover:to-pink-700'
                  }`}
              >
                <Play className="w-5 h-5 mr-2 fill-current" />
                {isPolling ? 'Optimizing...' : 'Run Solver'}
              </button>
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="bg-white rounded-3xl shadow-2xl border-2 border-gray-200 overflow-hidden min-h-[700px]">
          {/* Tabs */}
          <div className="flex border-b-4 border-gray-200 bg-gradient-to-r from-gray-50 via-blue-50 to-purple-50">
            {[
              { id: 'workers', label: '\ud83d\udc65 Workers', count: workersCRUD.workers.length },
              { id: 'shifts', label: '\ud83d\udcc5 Shifts', count: shiftsCRUD.shifts.length },
              { id: 'constraints', label: '\u2699\ufe0f Constraints', count: constraints.filter(c => c.enabled).length },
              { id: 'schedule', label: '\ud83d\udcca Schedule', count: solver.solverResult?.assignments?.length || 0 }
            ].map(tab => (
              <button
                key={tab.id}
                id={`tab-${tab.id}`}
                onClick={() => setActiveTab(tab.id)}
                className={`px-8 py-5 font-black text-lg border-b-4 transition-all ${activeTab === tab.id
                  ? 'border-indigo-600 text-indigo-700 bg-white shadow-lg'
                  : 'border-transparent text-gray-500 hover:bg-gray-100'
                  }`}
              >
                {tab.label} <span className="ml-2 px-3 py-1 bg-indigo-600 text-white rounded-full text-sm">{tab.count}</span>
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="p-8">
            {loading ? (
              <LoadingSpinner />
            ) : (
              <>
                {activeTab === 'workers' && (
                  <WorkersTab
                    workers={workersCRUD.workers}
                    onAddWorker={workersCRUD.openAddModal}
                    onEditWorker={workersCRUD.openEditModal}
                    onDeleteWorker={workersCRUD.handleDeleteWorker}
                    showToast={showToast}
                  />
                )}

                {activeTab === 'shifts' && (
                  <ShiftsTab
                    shifts={shiftsCRUD.shifts}
                    onAddShift={shiftsCRUD.openAddModal}
                    onEditShift={shiftsCRUD.openEditModal}
                    onDeleteShift={shiftsCRUD.handleDeleteShift}
                  />
                )}

                {activeTab === 'constraints' && (
                  <ConstraintsTab
                    constraints={constraints}
                    workers={workersCRUD.workers}
                    onAdd={(c) => setConstraints(prev => [...prev, c])}
                    onToggle={(id) => setConstraints(prev => prev.map(c => c.id === id ? { ...c, enabled: !c.enabled } : c))}
                    onRemove={(id) => setConstraints(prev => prev.filter(c => c.id !== id))}
                    onConstraintsReplace={setConstraints}
                  />
                )}

                {activeTab === 'schedule' && (
                  <ScheduleTab
                    assignments={solver.solverResult?.assignments || []}
                    objectiveValue={solver.solverResult?.objective_value}
                    theoreticalMax={solver.solverResult?.theoretical_max_score}
                    penaltyBreakdown={solver.solverResult?.penalty_breakdown}
                    workers={workersCRUD.workers}
                  />
                )}
              </>
            )}
          </div>
        </div>

        {/* Solver Diagnostics Panel */}
        {solver.solverResult && solver.solverResult.result_status !== 'Optimal' && (
          <SolverDiagnostics result={solver.solverResult} jobId={solver.solverResult.job_id} />
        )}
      </main>

      {/* Modals */}
      <AddWorkerModal
        isOpen={workersCRUD.isAddWorkerModalOpen}
        onClose={workersCRUD.closeModal}
        onAdd={workersCRUD.handleAddWorker}
        initialData={workersCRUD.editingWorker}
      />
      <AddShiftModal
        isOpen={shiftsCRUD.isAddShiftModalOpen}
        onClose={shiftsCRUD.closeModal}
        onAdd={shiftsCRUD.handleAddShift}
        initialData={shiftsCRUD.editingShift}
      />
    </div>
  );
}

export default App;
