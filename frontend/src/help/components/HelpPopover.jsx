import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Info } from 'lucide-react';
import { useHelp } from '../HelpProvider';

const placementClasses = {
    top: 'bottom-full mb-2 left-1/2 -translate-x-1/2',
    bottom: 'top-full mt-2 left-1/2 -translate-x-1/2',
    left: 'right-full mr-2 top-1/2 -translate-y-1/2',
    right: 'left-full ml-2 top-1/2 -translate-y-1/2',
};

const HelpPopover = ({ hintId, title, content, placement = 'top' }) => {
    const [isOpen, setIsOpen] = useState(false);
    const wrapperRef = useRef(null);
    const { getGlossaryTerm } = useHelp();

    const resolved = useMemo(() => {
        if (title && content) return { title, content };
        if (!hintId) return null;
        const term = getGlossaryTerm(hintId);
        return term ? { title: term.title, content: term.content } : null;
    }, [hintId, title, content, getGlossaryTerm]);

    useEffect(() => {
        const onClickOutside = (event) => {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', onClickOutside);
        return () => document.removeEventListener('mousedown', onClickOutside);
    }, []);

    if (!resolved) return null;

    return (
        <span className="relative inline-flex" ref={wrapperRef}>
            <button
                type="button"
                onClick={() => setIsOpen((prev) => !prev)}
                className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 text-blue-700 hover:bg-blue-200 transition-colors"
                aria-label={`Help for ${resolved.title}`}
            >
                <Info className="w-3.5 h-3.5" />
            </button>
            {isOpen && (
                <div
                    className={`absolute z-50 ${placementClasses[placement] || placementClasses.top} w-72 max-w-[80vw] bg-gray-900 text-white rounded-lg shadow-2xl px-3 py-2`}
                    role="tooltip"
                >
                    <div className="text-xs font-bold text-white mb-1">{resolved.title}</div>
                    <p className="text-xs text-gray-200 leading-5">{resolved.content}</p>
                </div>
            )}
        </span>
    );
};

export default HelpPopover;
