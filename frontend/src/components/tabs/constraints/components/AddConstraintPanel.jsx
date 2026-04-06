/**
 * @module constraints/components/AddConstraintPanel
 * @description Trigger panel for launching the add-constraint modal while
 *   preserving the existing inline editing flow for already-added constraints.
 */

import React from 'react';
import { Plus } from 'lucide-react';
import { HelpPopover } from '../../../../help';

/**
 * @param {Object} props
 * @param {Object[]} props.schemas - Available constraint schemas
 * @param {function} props.onOpen - Callback to open the add-constraint modal
 */
const AddConstraintPanel = React.memo(({ schemas, onOpen }) => {
    return (
        <div className="bg-gradient-to-r from-cyan-50 to-blue-50 p-4 rounded-xl border-2 border-cyan-200">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-cyan-900">
                <span className="font-semibold">Strictness:</span>
                <span>HARD / SOFT</span>
                <HelpPopover hintId="hard_constraint" />
                <HelpPopover hintId="soft_constraint" />
                <span className="font-semibold ml-2">Scope:</span>
                <span>STATIC / DYNAMIC</span>
                <HelpPopover hintId="static_constraint" />
                <HelpPopover hintId="dynamic_constraint" />
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="space-y-1">
                    <p className="font-semibold text-cyan-950">Build new constraints in a focused setup flow.</p>
                    <p className="text-sm text-cyan-800">
                        Select the type, choose HARD or SOFT, and fill the configuration before it appears in the list.
                    </p>
                </div>
                <button
                    id="constraints-add-trigger"
                    onClick={onOpen}
                    disabled={schemas.length === 0}
                    aria-label="Add constraint"
                    className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 px-4 py-3 font-bold text-white shadow-md hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
                >
                    <Plus className="w-4 h-4" />
                    Add a constraint
                </button>
            </div>
        </div>
    );
});

AddConstraintPanel.displayName = 'AddConstraintPanel';

export default AddConstraintPanel;
