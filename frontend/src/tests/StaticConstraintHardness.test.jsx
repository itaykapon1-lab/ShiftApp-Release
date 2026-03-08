import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import ConstraintsTab from '../components/tabs/constraints';

vi.mock('../api/endpoints', () => ({
  getConstraints: vi.fn(),
  getConstraintSchema: vi.fn(),
  updateConstraints: vi.fn(),
  clearAllConstraints: vi.fn(),
}));

import * as api from '../api/endpoints';

const staticSchema = [
  {
    key: 'max_hours_per_week',
    label: 'Max Hours Per Week',
    description: 'Maximum weekly hours per worker',
    constraint_type: 'SOFT',
    constraint_kind: 'STATIC',
    fields: [
      {
        name: 'max_hours',
        label: 'Max Hours',
        widget: 'number',
        type: 'number',
        default: 40,
      },
      {
        name: 'strictness',
        label: 'Strictness',
        widget: 'select',
        type: 'string',
        enum: ['HARD', 'SOFT'],
        default: 'SOFT',
      },
      {
        name: 'penalty',
        label: 'Penalty',
        widget: 'number',
        type: 'number',
        default: -50,
      },
    ],
  },
];

describe('Static constraint strictness UI behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConstraintSchema.mockResolvedValue(staticSchema);
    api.getConstraints.mockResolvedValue({ constraints: [] });
    api.updateConstraints.mockResolvedValue({ session_id: 's1', constraints: [] });
    api.clearAllConstraints.mockResolvedValue({});
  });

  it('shows SOFT strictness by default and zeros/dims penalty when switched to HARD', async () => {
    const user = userEvent.setup();

    render(
      <ConstraintsTab
        constraints={[
          {
            id: 'max-hours-1',
            category: 'max_hours_per_week',
            type: 'SOFT',
            enabled: true,
            name: 'Max hours per week',
            params: {
              max_hours: 40,
              penalty: -50,
              strictness: 'SOFT',
            },
          },
        ]}
        workers={[]}
      />
    );

    await waitFor(() => expect(api.getConstraintSchema).toHaveBeenCalledTimes(1));

    const globalSettings = screen
      .getByRole('heading', { name: 'Global Settings' })
      .closest('div.bg-white');
    expect(globalSettings).not.toBeNull();

    const strictnessSelect = screen.getByTitle('Constraint strictness');
    const penaltyInput = within(globalSettings).getByLabelText('Penalty');

    expect(strictnessSelect).toHaveValue('SOFT');
    expect(penaltyInput).toBeEnabled();

    fireEvent.change(penaltyInput, { target: { value: '-35' } });
    expect(penaltyInput).toHaveValue(-35);

    await user.selectOptions(strictnessSelect, 'HARD');

    expect(strictnessSelect).toHaveValue('HARD');
    expect(penaltyInput).toHaveValue(0);
    expect(screen.getByText(/Penalty disabled for HARD constraints/i)).toBeInTheDocument();
  });
});
