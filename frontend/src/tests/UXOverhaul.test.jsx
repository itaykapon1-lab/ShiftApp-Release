// ========================================
// UX OVERHAUL TESTS
// ========================================
// Tests for:
//   1. Day-Based Input (Pillar 1)
//   2. Opt-In Diagnostics (Pillar 2)
//   3. Visual Schedule Tab (Pillar 4)
// ========================================

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

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
    runDiagnostics: vi.fn(),
}));

// Mock the useJobPoller hook
vi.mock('../hooks/useJobPoller', () => ({
    default: () => ({
        jobId: 'test-job-123',
        jobStatus: null,
        isPolling: false,
        startPolling: vi.fn(),
        stopPolling: vi.fn(),
    }),
}));

// Import components for direct testing
import AddShiftModal from '../components/modals/AddShiftModal';
import SolverDiagnostics from '../components/SolverDiagnostics';
import ScheduleTab from '../components/tabs/ScheduleTab';
import ScoreIndicator from '../components/tabs/schedule/ScoreIndicator';
import * as api from '../api/endpoints';

// ========================================
// HELPERS
// ========================================

const setupEmptyState = () => {
    api.getWorkers.mockResolvedValue([]);
    api.getShifts.mockResolvedValue([]);
    api.getConstraints.mockResolvedValue({ constraints: [] });
};

// ========================================
// PILLAR 1: DAY-BASED INPUT TESTS
// ========================================

describe('Pillar 1: Day-Based Input', () => {
    it('renders a day dropdown instead of a date picker', () => {
        const onClose = vi.fn();
        const onAdd = vi.fn();

        render(
            <AddShiftModal
                isOpen={true}
                onClose={onClose}
                onAdd={onAdd}
                initialData={null}
            />
        );

        // Should have a dropdown with day options
        const daySelect = screen.getByRole('combobox');
        expect(daySelect).toBeInTheDocument();

        // Should contain day options
        const options = within(daySelect).getAllByRole('option');
        const optionValues = options.map(o => o.textContent);

        expect(optionValues).toContain('Sunday');
        expect(optionValues).toContain('Monday');
        expect(optionValues).toContain('Tuesday');
        expect(optionValues).toContain('Wednesday');
        expect(optionValues).toContain('Thursday');
        expect(optionValues).toContain('Friday');
        expect(optionValues).toContain('Saturday');
    });

    it('does NOT render a date picker input', () => {
        const onClose = vi.fn();
        const onAdd = vi.fn();

        render(
            <AddShiftModal
                isOpen={true}
                onClose={onClose}
                onAdd={onAdd}
                initialData={null}
            />
        );

        // Should NOT have a date input — verify no input[type="date"] exists
        const dateInputByType = document.querySelector('input[type="date"]');
        expect(dateInputByType).not.toBeInTheDocument();
    });

    it('defaults to Monday when creating a new shift', () => {
        const onClose = vi.fn();
        const onAdd = vi.fn();

        render(
            <AddShiftModal
                isOpen={true}
                onClose={onClose}
                onAdd={onAdd}
                initialData={null}
            />
        );

        const daySelect = screen.getByRole('combobox');
        expect(daySelect.value).toBe('Monday');
    });

    it('correctly maps day selection to dummy week date on submit', async () => {
        const onClose = vi.fn();
        const onAdd = vi.fn().mockResolvedValue({});
        const user = userEvent.setup();

        render(
            <AddShiftModal
                isOpen={true}
                onClose={onClose}
                onAdd={onAdd}
                initialData={null}
            />
        );

        // Fill in required fields
        const nameInput = screen.getByPlaceholderText(/Evening Service Shift/i);
        await user.type(nameInput, 'Test Shift');

        // Select Wednesday
        const daySelect = screen.getByRole('combobox');
        await user.selectOptions(daySelect, 'Wednesday');

        // Submit
        const submitButton = screen.getByRole('button', { name: /Create Shift/i });
        await user.click(submitButton);

        // Verify the payload contains the correct mapped date (Wednesday = 2026-01-07)
        await waitFor(() => {
            expect(onAdd).toHaveBeenCalledWith(
                expect.objectContaining({
                    start_time: expect.stringContaining('2026-01-07'),
                    end_time: expect.stringContaining('2026-01-07'),
                }),
                undefined
            );
        });
    });

    it('extracts day from existing shift date in edit mode', () => {
        const onClose = vi.fn();
        const onAdd = vi.fn();

        // Shift on a Friday
        const existingShift = {
            shift_id: 'S1',
            name: 'Existing Shift',
            start_time: '2026-01-09T14:00:00', // Friday in dummy week
            end_time: '2026-01-09T22:00:00',
            tasks_data: { tasks: [] },
        };

        render(
            <AddShiftModal
                isOpen={true}
                onClose={onClose}
                onAdd={onAdd}
                initialData={existingShift}
            />
        );

        const daySelect = screen.getByRole('combobox');
        expect(daySelect.value).toBe('Friday');
    });
});

// ========================================
// PILLAR 2: OPT-IN DIAGNOSTICS TESTS
// ========================================

describe('Pillar 2: Opt-In Diagnostics', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('shows "Run Diagnostics" button when no diagnosis is available', () => {
        // Simulating the actual data flow: job_id comes from solverResult
        const result = {
            job_id: 'job-123',
            result_status: 'Infeasible',
            diagnosis_message: null,
            violations: {},
        };

        render(<SolverDiagnostics result={result} jobId={result.job_id} />);

        const runButton = screen.getByRole('button', { name: /Run Diagnostics/i });
        expect(runButton).toBeInTheDocument();
    });

    it('does NOT show button when diagnosis is already available', () => {
        const result = {
            job_id: 'job-123',
            result_status: 'Infeasible',
            diagnosis_message: 'SKILL GAP: No workers have the "Chef" skill.',
            violations: {},
        };

        render(<SolverDiagnostics result={result} jobId={result.job_id} />);

        const runButton = screen.queryByRole('button', { name: /Run Diagnostics/i });
        expect(runButton).not.toBeInTheDocument();

        // Should show the diagnosis text instead
        expect(screen.getByText(/SKILL GAP/i)).toBeInTheDocument();
    });

    it('calls runDiagnostics API when button is clicked', async () => {
        const user = userEvent.setup();
        api.runDiagnostics.mockResolvedValue({
            diagnosis: 'FAILURE: Coverage constraint caused the infeasibility.',
        });

        const result = {
            job_id: 'job-123',
            result_status: 'Infeasible',
            diagnosis_message: null,
            violations: {},
        };

        render(<SolverDiagnostics result={result} jobId={result.job_id} />);

        const runButton = screen.getByRole('button', { name: /Run Diagnostics/i });
        await user.click(runButton);

        await waitFor(() => {
            expect(api.runDiagnostics).toHaveBeenCalledWith('job-123');
        });

        // Should show the diagnosis after loading
        await waitFor(() => {
            expect(screen.getByText(/Coverage constraint/i)).toBeInTheDocument();
        });
    });

    it('shows loading state while diagnostics are running', async () => {
        const user = userEvent.setup();

        // Make the API call hang
        api.runDiagnostics.mockImplementation(
            () => new Promise(resolve => setTimeout(() => resolve({ diagnosis: 'Done' }), 1000))
        );

        const result = {
            job_id: 'job-123',
            result_status: 'Infeasible',
            diagnosis_message: null,
            violations: {},
        };

        render(<SolverDiagnostics result={result} jobId={result.job_id} />);

        const runButton = screen.getByRole('button', { name: /Run Diagnostics/i });
        await user.click(runButton);

        // Should show "Analyzing..." text
        expect(screen.getByText(/Analyzing/i)).toBeInTheDocument();
    });

    it('does not render for Optimal results', () => {
        const result = {
            job_id: 'job-123',
            result_status: 'Optimal',
            assignments: [],
            objective_value: 100,
        };

        const { container } = render(<SolverDiagnostics result={result} jobId={result.job_id} />);

        // Should render nothing
        expect(container.firstChild).toBeNull();
    });
});

// ========================================
// PILLAR 4: VISUAL SCHEDULE TAB TESTS
// ========================================

describe('Pillar 4: Visual Schedule Tab', () => {
    it('renders empty state when no assignments', () => {
        render(<ScheduleTab assignments={[]} />);

        expect(screen.getByText(/No Schedule Available/i)).toBeInTheDocument();
        expect(screen.getByText(/Run the solver/i)).toBeInTheDocument();
    });

    it('renders week grid with assignments grouped by day (ISO format)', () => {
        const assignments = [
            {
                worker_name: 'Alice',
                shift_name: 'Morning Shift',
                time: '2026-01-05T08:00:00', // Monday (ISO format)
                task: 'Service',
                score: 10,
                score_breakdown: '+10 (Pref)',
            },
            {
                worker_name: 'Bob',
                shift_name: 'Evening Shift',
                time: '2026-01-07T18:00:00', // Wednesday (ISO format)
                task: 'Kitchen',
                score: -5,
                score_breakdown: '-5 (Avoid)',
            },
        ];

        render(<ScheduleTab assignments={assignments} objectiveValue={5} theoreticalMax={15} />);

        // Should show both shifts
        expect(screen.getByText('Morning Shift')).toBeInTheDocument();
        expect(screen.getByText('Evening Shift')).toBeInTheDocument();

        // Should show worker names
        expect(screen.getByText('Alice')).toBeInTheDocument();
        expect(screen.getByText('Bob')).toBeInTheDocument();

        // Should show day headers
        expect(screen.getByText('MON')).toBeInTheDocument();
        expect(screen.getByText('WED')).toBeInTheDocument();
    });

    it('renders week grid with assignments grouped by day (day abbreviation format)', () => {
        // This is the actual format from the backend: "Mon 08:00 - 16:00"
        const assignments = [
            {
                worker_name: 'Alice',
                shift_name: 'Morning Shift',
                time: 'Mon 08:00 - 16:00', // Day abbreviation format
                task: 'Service',
                score: 10,
                score_breakdown: '+10 (Pref)',
            },
            {
                worker_name: 'Bob',
                shift_name: 'Evening Shift',
                time: 'Wed 18:00 - 23:00', // Day abbreviation format
                task: 'Kitchen',
                score: -5,
                score_breakdown: '-5 (Avoid)',
            },
        ];

        render(<ScheduleTab assignments={assignments} objectiveValue={5} theoreticalMax={15} />);

        // Should show both shifts
        expect(screen.getByText('Morning Shift')).toBeInTheDocument();
        expect(screen.getByText('Evening Shift')).toBeInTheDocument();

        // Should show worker names
        expect(screen.getByText('Alice')).toBeInTheDocument();
        expect(screen.getByText('Bob')).toBeInTheDocument();

        // Should show day headers (columns should be highlighted)
        expect(screen.getByText('MON')).toBeInTheDocument();
        expect(screen.getByText('WED')).toBeInTheDocument();
    });

    it('displays total score and efficiency', () => {
        const assignments = [
            {
                worker_name: 'Alice',
                shift_name: 'Shift A',
                time: '2026-01-05T08:00:00',
                task: 'Task',
                score: 15,
            },
        ];

        render(
            <ScheduleTab
                assignments={assignments}
                objectiveValue={75.5}
                theoreticalMax={100}
            />
        );

        // Should show total score
        expect(screen.getByText('75.5')).toBeInTheDocument();

        // Should show efficiency percentage
        expect(screen.getByText('75.5%')).toBeInTheDocument();
    });

    it('displays assignment count in header', () => {
        const assignments = [
            { worker_name: 'A', shift_name: 'S1', time: '2026-01-05T08:00:00', task: 'T', score: 0 },
            { worker_name: 'B', shift_name: 'S1', time: '2026-01-05T08:00:00', task: 'T', score: 0 },
            { worker_name: 'C', shift_name: 'S2', time: '2026-01-06T08:00:00', task: 'T', score: 0 },
        ];

        render(<ScheduleTab assignments={assignments} />);

        // Should show "3 assignments across 2 shifts with 3 workers"
        expect(screen.getByText(/3 assignments/i)).toBeInTheDocument();
    });
});

// ========================================
// SCORE INDICATOR TESTS
// ========================================

describe('ScoreIndicator Component', () => {
    it('renders positive score with green styling', () => {
        render(<ScoreIndicator score={10} breakdown="+10 (Pref)" />);

        const badge = screen.getByText('+10');
        expect(badge).toBeInTheDocument();
        expect(badge.className).toContain('text-green');
    });

    it('renders negative score with red styling', () => {
        render(<ScoreIndicator score={-5} breakdown="-5 (Avoid)" />);

        const badge = screen.getByText('-5');
        expect(badge).toBeInTheDocument();
        expect(badge.className).toContain('text-red');
    });

    it('renders zero score with gray styling', () => {
        render(<ScoreIndicator score={0} />);

        const badge = screen.getByText('0');
        expect(badge).toBeInTheDocument();
        expect(badge.className).toContain('text-gray');
    });

    it('shows tooltip on hover when breakdown is provided', async () => {
        const user = userEvent.setup();

        render(<ScoreIndicator score={10} breakdown="+10 (Pref)" />);

        const badge = screen.getByText('+10');

        // Hover over the badge
        await user.hover(badge);

        // Tooltip should appear
        await waitFor(() => {
            expect(screen.getByText('Score Breakdown')).toBeInTheDocument();
            expect(screen.getByText('+10 (Pref)')).toBeInTheDocument();
        });
    });
});
