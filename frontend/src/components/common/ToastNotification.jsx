/**
 * ToastNotification — Animated, auto-dismissing notification bar.
 * Renders a premium success/error/info/warning toast with a progress bar
 * that counts down to auto-dismiss.
 *
 * Extracted from App.jsx for better modularity.
 */

import React, { useEffect, useRef } from 'react';
import { CheckCircle, AlertCircle, X, Info } from 'lucide-react';

const TOAST_DURATION = 5000; // 5 seconds

const ToastNotification = ({ toast, onDismiss }) => {
    const timerRef = useRef(null);
    const isParsingAlert = Boolean(
        toast &&
        toast.category === 'parsing' &&
        (toast.type === 'error' || toast.type === 'warning')
    );
    const isPersistent = Boolean(toast?.persist || isParsingAlert);
    const detailItems = Array.isArray(toast?.details)
        ? toast.details.filter(Boolean)
        : [];

    useEffect(() => {
        if (!toast) {
            return;
        }

        if (isPersistent) {
            return undefined;
        }

        timerRef.current = setTimeout(() => {
            onDismiss();
        }, TOAST_DURATION);

        return () => {
            clearTimeout(timerRef.current);
        };
    }, [toast, onDismiss, isPersistent]);

    if (!toast) return null;

    const baseStyles = {
        success: {
            bg: 'bg-gradient-to-r from-emerald-500 to-green-500',
            text: 'text-white',
            border: 'border-emerald-300',
            icon: <CheckCircle className="w-6 h-6" />,
            detailText: 'text-sm opacity-90',
            closeHover: 'hover:bg-white/20',
            progressBg: 'bg-emerald-300',
        },
        error: {
            bg: 'bg-gradient-to-r from-red-500 to-rose-500',
            text: 'text-white',
            border: 'border-red-300',
            icon: <AlertCircle className="w-6 h-6" />,
            detailText: 'text-sm opacity-90',
            closeHover: 'hover:bg-white/20',
            progressBg: 'bg-red-300',
        },
        warning: {
            bg: 'bg-gradient-to-r from-amber-500 to-yellow-500',
            text: 'text-white',
            border: 'border-amber-300',
            icon: <AlertCircle className="w-6 h-6" />,
            detailText: 'text-sm opacity-90',
            closeHover: 'hover:bg-white/20',
            progressBg: 'bg-amber-300',
        },
        info: {
            bg: 'bg-gradient-to-r from-blue-500 to-indigo-500',
            text: 'text-white',
            border: 'border-blue-300',
            icon: <Info className="w-6 h-6" />,
            detailText: 'text-sm opacity-90',
            closeHover: 'hover:bg-white/20',
            progressBg: 'bg-blue-300',
        }
    };

    const parsingStyles = {
        error: {
            bg: 'bg-red-100',
            text: 'text-red-900',
            border: 'border-red-400',
            icon: <AlertCircle className="w-7 h-7 text-red-700" />,
            detailText: 'text-base text-red-900',
            closeHover: 'hover:bg-red-200',
            progressBg: 'bg-red-300',
        },
        warning: {
            bg: 'bg-amber-100',
            text: 'text-amber-900',
            border: 'border-amber-400',
            icon: <AlertCircle className="w-7 h-7 text-amber-700" />,
            detailText: 'text-base text-amber-900',
            closeHover: 'hover:bg-amber-200',
            progressBg: 'bg-amber-300',
        },
    };

    const style = isParsingAlert
        ? parsingStyles[toast.type]
        : (baseStyles[toast.type] || baseStyles.info);
    const widthClass = isParsingAlert
        ? 'w-[560px] max-w-[calc(100vw-1.5rem)]'
        : 'w-[420px] max-w-[calc(100vw-3rem)]';
    const bodyClass = isParsingAlert
        ? 'flex items-start gap-4 px-6 py-5'
        : 'flex items-start gap-3 px-5 py-4';
    const messageClass = isParsingAlert
        ? 'font-extrabold text-lg leading-snug'
        : 'font-bold text-base leading-snug';

    return (
        <div
            id="toast-notification"
            role="alert"
            aria-live="assertive"
            className={`fixed top-6 right-6 z-[100] ${widthClass} transition-all duration-300 ease-out translate-x-0 opacity-100`}
        >
            <div className={`${style.bg} ${style.text} rounded-2xl shadow-2xl border-2 ${style.border} overflow-hidden`}>
                <div className={bodyClass}>
                    <div className="flex-shrink-0 mt-0.5">{style.icon}</div>
                    <div className="flex-1 min-w-0">
                        <p className={messageClass}>{toast.message}</p>
                        {detailItems.length > 0 ? (
                            <ul className={`mt-2 list-disc pl-6 space-y-1 ${style.detailText}`}>
                                {detailItems.map((line, index) => (
                                    <li key={`${toast.key || toast.message}-${index}`}>{line}</li>
                                ))}
                            </ul>
                        ) : toast.detail && (
                            <p className={`${style.detailText} mt-2 whitespace-pre-line`}>{toast.detail}</p>
                        )}
                    </div>
                    <button
                        onClick={onDismiss}
                        className={`flex-shrink-0 ${style.closeHover} rounded-full p-1 transition-colors`}
                        aria-label="Dismiss notification"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>
                {!isPersistent && (
                    <div className="h-1 bg-white/20">
                        <div
                            className={`h-full ${style.progressBg}`}
                            style={{ width: '100%', animation: `toast-progress ${TOAST_DURATION}ms linear forwards` }}
                        />
                    </div>
                )}
            </div>
        </div>
    );
};

export default ToastNotification;
