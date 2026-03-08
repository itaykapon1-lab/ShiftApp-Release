import React from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AddShiftModal from '../components/modals/AddShiftModal';


const renderShiftModal = ({ onAdd, initialData = null } = {}) => {
    const onClose = vi.fn();
    const addHandler = onAdd || vi.fn().mockResolvedValue({});

    render(
        <AddShiftModal
            isOpen={true}
            onClose={onClose}
            onAdd={addHandler}
            initialData={initialData}
        />
    );

    return { onClose, onAdd: addHandler };
};


afterEach(() => {
    vi.restoreAllMocks();
});


describe('Task Option Priority UI', () => {
    it('hides priority dropdown for single option', () => {
        renderShiftModal();

        expect(screen.queryByLabelText(/Priority/i)).not.toBeInTheDocument();
    });

    it('shows priority dropdown for multiple options, defaulting to #1', async () => {
        const user = userEvent.setup();
        renderShiftModal();

        await user.click(screen.getByRole('button', { name: /Add Option/i }));

        const prioritySelects = screen.getAllByLabelText(/Priority/i);
        expect(prioritySelects).toHaveLength(2);
        prioritySelects.forEach((select) => {
            expect(select).toHaveDisplayValue('#1');
        });
    });

    it('sends selected option priority in the save payload', async () => {
        const user = userEvent.setup();
        const onAdd = vi.fn().mockResolvedValue({});
        renderShiftModal({ onAdd });

        await user.type(
            screen.getByPlaceholderText(/Evening Service Shift/i),
            'Priority Payload Shift'
        );
        await user.click(screen.getByRole('button', { name: /Add Option/i }));

        const prioritySelects = screen.getAllByLabelText(/Priority/i);
        await user.selectOptions(prioritySelects[1], '3');
        await user.click(screen.getByRole('button', { name: /Create Shift/i }));

        await waitFor(() => {
            expect(onAdd).toHaveBeenCalledTimes(1);
        });

        const payload = onAdd.mock.calls[0][0];
        expect(payload.tasks_data.tasks[0].options[0].priority).toBe(1);
        expect(payload.tasks_data.tasks[0].options[1].priority).toBe(3);
    });

    it('warns with window.confirm if no option has priority #1 before saving', async () => {
        const user = userEvent.setup();
        const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
        const onAdd = vi.fn().mockResolvedValue({});
        renderShiftModal({ onAdd });

        await user.type(
            screen.getByPlaceholderText(/Evening Service Shift/i),
            'Priority Validation Shift'
        );
        await user.click(screen.getByRole('button', { name: /Add Option/i }));

        const prioritySelects = screen.getAllByLabelText(/Priority/i);
        await user.selectOptions(prioritySelects[0], '2');
        await user.selectOptions(prioritySelects[1], '2');
        await user.click(screen.getByRole('button', { name: /Create Shift/i }));

        expect(confirmSpy).toHaveBeenCalledWith(expect.stringMatching(/#1/i));
    });

    it('loads existing priority in edit mode', () => {
        const initialData = {
            shift_id: 's1',
            name: 'Edit Shift',
            start_time: '2024-01-01T08:00:00',
            end_time: '2024-01-01T16:00:00',
            tasks_data: {
                tasks: [{
                    task_id: 'task_1',
                    name: 'Test Task',
                    options: [
                        { preference_score: 0, priority: 1, requirements: [{ count: 1, required_skills: {} }] },
                        { preference_score: 0, priority: 2, requirements: [{ count: 1, required_skills: {} }] },
                    ]
                }]
            },
        };

        renderShiftModal({ initialData });

        const prioritySelects = screen.getAllByLabelText(/Priority/i);
        expect(prioritySelects).toHaveLength(2);
        expect(prioritySelects[0]).toHaveDisplayValue('#1');
        expect(prioritySelects[1]).toHaveDisplayValue('#2');
    });

    it('defaults to priority 1 for legacy data without priority field', () => {
        const initialData = {
            shift_id: 's1',
            name: 'Legacy Shift',
            start_time: '2024-01-01T08:00:00',
            end_time: '2024-01-01T16:00:00',
            tasks_data: {
                tasks: [{
                    task_id: 'task_1',
                    name: 'Legacy Task',
                    options: [
                        { preference_score: 0, requirements: [{ count: 1, required_skills: {} }] },
                        { preference_score: 0, requirements: [{ count: 1, required_skills: {} }] },
                    ]
                }]
            },
        };

        renderShiftModal({ initialData });

        const prioritySelects = screen.getAllByLabelText(/Priority/i);
        expect(prioritySelects).toHaveLength(2);
        prioritySelects.forEach((select) => {
            expect(select).toHaveDisplayValue('#1');
        });
    });

    it('does not trigger confirm when at least one option is priority #1', async () => {
        const user = userEvent.setup();
        const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
        const onAdd = vi.fn().mockResolvedValue({});
        renderShiftModal({ onAdd });

        await user.type(
            screen.getByPlaceholderText(/Evening Service Shift/i),
            'No Warning Shift'
        );
        await user.click(screen.getByRole('button', { name: /Add Option/i }));

        // First option stays at #1, second goes to #3
        const prioritySelects = screen.getAllByLabelText(/Priority/i);
        await user.selectOptions(prioritySelects[1], '3');
        await user.click(screen.getByRole('button', { name: /Create Shift/i }));

        await waitFor(() => {
            expect(onAdd).toHaveBeenCalledTimes(1);
        });
        expect(confirmSpy).not.toHaveBeenCalled();
    });
});
