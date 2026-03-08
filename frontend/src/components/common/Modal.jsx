// ========================================
// MODAL COMPONENT - Reusable & Accessible
// ========================================

import React, { useEffect, useRef, useCallback } from 'react';
import { X } from 'lucide-react';

const Modal = ({ isOpen, onClose, title, children, size = 'md' }) => {
    const modalRef = useRef(null);
    const previousActiveElement = useRef(null);

    // Handle Escape key to close modal
    const handleKeyDown = useCallback((event) => {
        if (event.key === 'Escape') {
            onClose();
        }
    }, [onClose]);

    // Focus trap - keep focus within modal
    const handleTabKey = useCallback((event) => {
        if (event.key !== 'Tab' || !modalRef.current) return;

        const focusableElements = modalRef.current.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (event.shiftKey && document.activeElement === firstElement) {
            event.preventDefault();
            lastElement?.focus();
        } else if (!event.shiftKey && document.activeElement === lastElement) {
            event.preventDefault();
            firstElement?.focus();
        }
    }, []);

    // Setup/cleanup focus management and keyboard listeners
    useEffect(() => {
        if (isOpen) {
            // Store the currently focused element to restore later
            previousActiveElement.current = document.activeElement;

            // Add event listeners
            document.addEventListener('keydown', handleKeyDown);
            document.addEventListener('keydown', handleTabKey);

            // Focus the modal container
            setTimeout(() => {
                modalRef.current?.focus();
            }, 0);

            // Prevent body scroll when modal is open
            document.body.style.overflow = 'hidden';
        }

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.removeEventListener('keydown', handleTabKey);
            document.body.style.overflow = '';

            // Restore focus to the previously focused element
            if (previousActiveElement.current && typeof previousActiveElement.current.focus === 'function') {
                previousActiveElement.current.focus();
            }
        };
    }, [isOpen, handleKeyDown, handleTabKey]);

    if (!isOpen) return null;

    const widthClass = size === 'lg' ? 'max-w-4xl' : size === 'xl' ? 'max-w-6xl' : 'max-w-2xl';

    // Handle click on backdrop to close
    const handleBackdropClick = (event) => {
        if (event.target === event.currentTarget) {
            onClose();
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 backdrop-blur-sm p-4"
            onClick={handleBackdropClick}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
        >
            <div
                ref={modalRef}
                tabIndex={-1}
                className={`bg-white rounded-2xl shadow-2xl w-full ${widthClass} overflow-hidden max-h-[90vh] flex flex-col outline-none`}
            >
                <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-4 flex justify-between items-center">
                    <h2 id="modal-title" className="text-xl font-bold text-white">{title}</h2>
                    <button
                        onClick={onClose}
                        className="text-white hover:bg-white hover:bg-opacity-20 rounded-full p-2 transition-all"
                        aria-label="Close modal"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>
                <div className="p-6 overflow-y-auto flex-1">{children}</div>
            </div>
        </div>
    );
};

export default Modal;
