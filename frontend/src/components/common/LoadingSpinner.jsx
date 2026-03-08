// ========================================
// LOADING SPINNER COMPONENT
// ========================================

import React from 'react';
import { RefreshCw } from 'lucide-react';

const LoadingSpinner = ({ message = 'Loading data...' }) => {
    return (
        <div className="flex flex-col items-center justify-center h-96">
            <RefreshCw className="w-16 h-16 animate-spin text-indigo-600 mb-4" />
            <p className="text-2xl font-bold text-gray-400">{message}</p>
        </div>
    );
};

export default LoadingSpinner;
