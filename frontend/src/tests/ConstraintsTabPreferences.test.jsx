import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ConstraintsTab from '../components/tabs/constraints';

vi.mock('../api/endpoints', () => ({
  getConstraints: vi.fn(),
  getConstraintSchema: vi.fn(),
  updateConstraints: vi.fn(),
}));

import * as api from '../api/endpoints';

const workerPreferencesSchema = [
  {
    key: 'worker_preferences',
    label: 'Worker Preferences',
    description: 'Reward preferred shifts and penalize unwanted shifts',
    constraint_type: 'SOFT',
    constraint_kind: 'STATIC',
    fields: [
      {
        name: 'enabled',
        label: 'Enable worker preferences',
        widget: 'checkbox',
        type: 'boolean',
        default: true,
        required: false,
        order: 10,
      },
      {
        name: 'preference_reward',
        label: 'Reward points (preferred shifts)',
        widget: 'number',
        type: 'number',
        default: 10,
        required: false,
        order: 20,
      },
      {
        name: 'preference_penalty',
        label: 'Penalty points (unwanted shifts)',
        widget: 'number',
        type: 'number',
        default: -100,
        required: false,
        order: 30,
      },
    ],
  },
];

describe('ConstraintsTab worker preference weights', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getConstraintSchema.mockResolvedValue(workerPreferencesSchema);
    api.getConstraints.mockResolvedValue({ constraints: [] });
    api.updateConstraints.mockResolvedValue({ session_id: 's1', constraints: [] });
  });

  it('renders reward/penalty fields and saves updated values through updateConstraints', async () => {
    const user = userEvent.setup();

    render(
      <ConstraintsTab
        constraints={[
          {
            id: 'pref-1',
            category: 'worker_preferences',
            type: 'SOFT',
            enabled: true,
            name: 'Worker Preferences',
            description: 'Reward preferred shifts and penalize unwanted shifts',
            params: {
              enabled: true,
              preference_reward: 10,
              preference_penalty: -100,
            },
          },
        ]}
        workers={[]}
      />
    );

    await waitFor(() => expect(api.getConstraintSchema).toHaveBeenCalledTimes(1));

    const globalSettingsSection = screen
      .getByRole('heading', { name: 'Global Settings' })
      .closest('div.bg-white');

    expect(globalSettingsSection).not.toBeNull();

    const rewardInput = within(globalSettingsSection).getByLabelText('Reward points (preferred shifts)');
    const penaltyInput = within(globalSettingsSection).getByLabelText('Penalty points (unwanted shifts)');

    expect(rewardInput).toHaveValue(10);
    expect(penaltyInput).toHaveValue(-100);

    const saveButton = within(globalSettingsSection).getByRole('button', { name: /Save Changes/i });
    expect(saveButton).toBeDisabled();

    fireEvent.change(rewardInput, { target: { value: '25' } });
    fireEvent.change(penaltyInput, { target: { value: '-50' } });

    expect(rewardInput).toHaveValue(25);
    expect(penaltyInput).toHaveValue(-50);
    expect(saveButton).toBeEnabled();

    await user.click(saveButton);

    await waitFor(() => expect(api.updateConstraints).toHaveBeenCalledTimes(1));
    expect(api.updateConstraints).toHaveBeenCalledWith([
      {
        id: 'pref-1',
        category: 'worker_preferences',
        type: 'SOFT',
        enabled: true,
        name: 'Worker Preferences',
        description: 'Reward preferred shifts and penalize unwanted shifts',
        params: {
          enabled: true,
          preference_reward: 25,
          preference_penalty: -50,
        },
      },
    ]);
  });
});
