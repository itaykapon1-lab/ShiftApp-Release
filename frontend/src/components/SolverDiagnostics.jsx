// ========================================
// SOLVER DIAGNOSTICS - Display Component
// Now with OPT-IN diagnostics support
// ========================================

import React, { useState, useRef, useEffect, useMemo } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle, XCircle, Info, Search, Loader2 } from 'lucide-react';
import { runDiagnostics, getJobStatus } from '../api/endpoints';
import { formatDiagnosticMessage } from '../utils/displayFormatting';

/**
 * SolverDiagnostics Component
 *
 * Displays diagnostic information when the solver returns:
 * - Infeasible: No solution found (with opt-in diagnosis button)
 * - Feasible: Suboptimal solution (with violations and score comparison)
 *
 * Props:
 * - result: Object containing solver result data
 *   - result_status: "Optimal" | "Feasible" | "Infeasible"
 *   - diagnosis_message: String explaining why infeasible (optional, may be null until requested)
 *   - violations: Dict of constraint violations (optional)
 *   - objective_value: Actual score achieved
 *   - theoretical_max_score: Best possible score
 * - jobId: The job ID for triggering diagnostics
 * - onDiagnosisComplete: Optional callback when diagnosis is fetched
 */
const SolverDiagnostics = ({ result, jobId, onDiagnosisComplete, workers = [] }) => {
    const [diagnosis, setDiagnosis] = useState(result?.diagnosis_message || null);
    const [diagnosisStatus, setDiagnosisStatus] = useState(result?.diagnosis_status || null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const isMountedRef = useRef(true);
    const formattedDiagnosis = useMemo(
        () => formatDiagnosticMessage(diagnosis, workers),
        [diagnosis, workers]
    );
    const formattedError = useMemo(
        () => formatDiagnosticMessage(error, workers),
        [error, workers]
    );

    useEffect(() => {
        setDiagnosis(result?.diagnosis_message || null);
        setDiagnosisStatus(result?.diagnosis_status || null);
        setError(null);
        setIsLoading(false);
    }, [jobId, result?.diagnosis_message, result?.diagnosis_status]);

    useEffect(() => {
        return () => { isMountedRef.current = false; };
    }, []);

    // Don't render if no result or optimal solution
    if (!result || result.result_status === 'Optimal') {
        return null;
    }

    const isInfeasible = result.result_status === 'Infeasible';

    // Calculate efficiency percentage if we have both scores
    const efficiency = (result.theoretical_max_score && result.objective_value)
        ? ((result.objective_value / result.theoretical_max_score) * 100).toFixed(1)
        : null;

    const handleRunDiagnostics = async () => {
        if (!jobId) {
            setError('No job ID available for diagnostics');
            return;
        }

        setIsLoading(true);
        setDiagnosis(null);
        setDiagnosisStatus('PENDING');
        setError(null);

        try {
            // Step 1: Trigger async diagnostics (returns 202)
            const enqueueResult = await runDiagnostics(jobId);
            if (!isMountedRef.current) return;
            setDiagnosisStatus(enqueueResult?.diagnosis_status || 'PENDING');

            // Step 2: Poll GET /status/{jobId} until diagnosis is terminal
            const POLL_MS = 1500;
            const MAX_ATTEMPTS = 40; // 60s timeout (mitigates executor starvation)

            for (let i = 0; i < MAX_ATTEMPTS; i++) {
                await new Promise(r => setTimeout(r, POLL_MS));
                if (!isMountedRef.current) return;

                const status = await getJobStatus(jobId);
                if (!isMountedRef.current) return;
                setDiagnosisStatus(status.diagnosis_status || null);

                if (status.diagnosis_status === 'COMPLETED') {
                    setDiagnosis(status.diagnosis_message || null);
                    setError(null);
                    if (onDiagnosisComplete) {
                        onDiagnosisComplete(status.diagnosis_message);
                    }
                    return;
                }
                if (status.diagnosis_status === 'FAILED') {
                    setDiagnosis(status.diagnosis_message || null);
                    setError(status.diagnosis_message || 'Diagnostics failed. Please try again.');
                    return;
                }
            }
            if (!isMountedRef.current) return;
            setDiagnosisStatus('FAILED');
            setError('Diagnostics timed out. Please try again.');
        } catch (err) {
            console.error('Diagnostics failed:', err);
            if (!isMountedRef.current) return;
            setDiagnosisStatus('FAILED');
            setError(err.message || 'Failed to run diagnostics');
        } finally {
            if (isMountedRef.current) {
                setIsLoading(false);
            }
        }
    };

    const showPersistedDiagnosis = Boolean(diagnosis) && diagnosisStatus !== 'PENDING' && diagnosisStatus !== 'RUNNING';
    const showLoadingState = isLoading || diagnosisStatus === 'PENDING' || diagnosisStatus === 'RUNNING';
    const showRetryButton = diagnosisStatus === null || diagnosisStatus === 'FAILED';

    return (
        <div className={`mt-6 rounded-2xl border-4 overflow-hidden shadow-xl ${isInfeasible
                ? 'border-red-400 bg-red-50'
                : 'border-yellow-400 bg-yellow-50'
            }`}>
            {/* Header */}
            <div className={`px-6 py-4 flex items-center gap-3 ${isInfeasible
                    ? 'bg-red-600 text-white'
                    : 'bg-yellow-500 text-white'
                }`}>
                {isInfeasible ? (
                    <XCircle className="w-7 h-7" />
                ) : (
                    <AlertTriangle className="w-7 h-7" />
                )}
                <h3 className="text-xl font-black">
                    {isInfeasible ? 'No Solution Found' : 'Suboptimal Solution'}
                </h3>
            </div>

            {/* Content */}
            <div className="p-6 space-y-4">
                {/* Diagnosis Section */}
                {isInfeasible && (
                    <div className="bg-white rounded-xl border-2 border-gray-200 p-4">
                        <div className="flex items-start gap-3">
                            <Info className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
                            <div className="flex-1">
                                <h4 className="font-bold text-gray-800 mb-2">Diagnosis:</h4>

                                {showPersistedDiagnosis ? (
                                    <div className="space-y-3">
                                        <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 p-3 rounded-lg border">
                                            {formattedDiagnosis}
                                        </pre>

                                        {showRetryButton && (
                                            <button
                                                onClick={handleRunDiagnostics}
                                                disabled={isLoading}
                                                className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-white transition-all ${isLoading
                                                        ? 'bg-gray-400 cursor-not-allowed'
                                                        : 'bg-blue-600 hover:bg-blue-700 hover:scale-105'
                                                    }`}
                                            >
                                                <Search className="w-5 h-5" />
                                                {diagnosisStatus === 'FAILED' ? 'Retry Diagnostics' : 'Run Diagnostics'}
                                            </button>
                                        )}
                                    </div>
                                ) : (
                                    <div className="space-y-3">
                                        {showRetryButton && (
                                            <p className="text-sm text-gray-600">
                                                Click the button below to analyze why no solution was found.
                                                This will identify which constraints are causing the conflict.
                                            </p>
                                        )}

                                        {error && (
                                            <div className="text-sm text-red-600 bg-red-50 p-2 rounded border border-red-200">
                                                {formattedError}
                                            </div>
                                        )}

                                        {showLoadingState && (
                                            <div className="flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-white bg-gray-500">
                                                <Loader2 className="w-5 h-5 animate-spin" />
                                                Analyzing...
                                            </div>
                                        )}

                                        {showRetryButton && (
                                            <button
                                                onClick={handleRunDiagnostics}
                                                disabled={isLoading}
                                                className={`flex items-center gap-2 px-4 py-2 rounded-lg font-bold text-white transition-all ${isLoading
                                                        ? 'bg-gray-400 cursor-not-allowed'
                                                        : 'bg-blue-600 hover:bg-blue-700 hover:scale-105'
                                                    }`}
                                            >
                                                <Search className="w-5 h-5" />
                                                {diagnosisStatus === 'FAILED' ? 'Retry Diagnostics' : 'Run Diagnostics'}
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Violations List */}
                {result.violations && Object.keys(result.violations).length > 0 && (
                    <div className="bg-white rounded-xl border-2 border-gray-200 p-4">
                        <div className="flex items-start gap-3">
                            <AlertCircle className="w-5 h-5 text-orange-600 mt-0.5 flex-shrink-0" />
                            <div className="flex-1">
                                <h4 className="font-bold text-gray-800 mb-2">Constraint Violations:</h4>
                                <ul className="space-y-2">
                                    {Object.entries(result.violations).map(([name, details]) => (
                                        <li key={name} className="flex items-start gap-2 text-sm">
                                            <span className="w-2 h-2 bg-orange-500 rounded-full mt-1.5 flex-shrink-0"></span>
                                            <div>
                                                <span className="font-semibold text-gray-800">{name}:</span>
                                                <span className="text-gray-600 ml-1">
                                                    {typeof details === 'object'
                                                        ? `${Array.isArray(details) ? details.length : 1} occurrence(s)`
                                                        : formatDiagnosticMessage(String(details), workers)
                                                    }
                                                </span>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        </div>
                    </div>
                )}

                {/* Score Comparison */}
                {efficiency && (
                    <div className="bg-white rounded-xl border-2 border-gray-200 p-4">
                        <div className="flex items-start gap-3">
                            <CheckCircle className={`w-5 h-5 mt-0.5 flex-shrink-0 ${parseFloat(efficiency) >= 80 ? 'text-green-600' :
                                    parseFloat(efficiency) >= 50 ? 'text-yellow-600' : 'text-red-600'
                                }`} />
                            <div className="flex-1">
                                <h4 className="font-bold text-gray-800 mb-2">Solution Quality:</h4>
                                <div className="flex items-center gap-4">
                                    <div className="flex-1">
                                        <div className="w-full bg-gray-200 rounded-full h-4 overflow-hidden">
                                            <div
                                                className={`h-full rounded-full transition-all duration-500 ${parseFloat(efficiency) >= 80 ? 'bg-green-500' :
                                                        parseFloat(efficiency) >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                                                    }`}
                                                style={{ width: `${Math.min(100, parseFloat(efficiency))}%` }}
                                            />
                                        </div>
                                    </div>
                                    <div className="text-right min-w-[120px]">
                                        <span className="text-2xl font-black text-gray-800">{efficiency}%</span>
                                        <p className="text-xs text-gray-500">
                                            {result.objective_value?.toFixed(1)} / {result.theoretical_max_score?.toFixed(1)}
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* Help Text */}
                <div className="text-sm text-gray-600 bg-gray-100 rounded-lg p-3">
                    <strong>Tip:</strong> {isInfeasible
                        ? 'Try relaxing constraints, adding more workers, or adjusting shift requirements.'
                        : 'The solver found a valid schedule but couldn\'t optimize all preferences. Review violations above.'
                    }
                </div>
            </div>
        </div>
    );
};

export default SolverDiagnostics;
