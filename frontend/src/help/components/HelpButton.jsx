import React from 'react';
import { CircleHelp } from 'lucide-react';
import { useHelp } from '../context';

const variantClasses = {
    subtle: 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50',
    primary: 'bg-indigo-600 border-indigo-700 text-white hover:bg-indigo-700',
    neutral: 'bg-gray-100 border-gray-200 text-gray-700 hover:bg-gray-200',
};

const HelpButton = ({ topicId, label = 'Help', variant = 'subtle', placement = 'inline' }) => {
    const { openHelp } = useHelp();
    const cls = variantClasses[variant] || variantClasses.subtle;
    const placementCls = placement === 'inline' ? '' : 'ml-auto';

    return (
        <button
            type="button"
            onClick={() => openHelp(topicId)}
            className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-semibold transition-colors ${cls} ${placementCls}`}
            aria-label={label}
        >
            <CircleHelp className="w-4 h-4" />
            <span>{label}</span>
        </button>
    );
};

export default HelpButton;
