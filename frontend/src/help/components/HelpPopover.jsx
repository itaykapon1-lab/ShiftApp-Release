import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Info } from 'lucide-react';
import { useHelp } from '../context';
import useTooltipPosition from '../tour/useTooltipPosition';

const HelpPopover = ({ hintId, title, content, placement = 'top' }) => {
    const [isOpen, setIsOpen] = useState(false);
    const wrapperRef = useRef(null);
    const triggerRef = useRef(null);
    const { getGlossaryTerm } = useHelp();
    const { top, left, setCardRef } = useTooltipPosition(triggerRef.current, placement, isOpen);

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

        const onKeyDown = (event) => {
            if (event.key === 'Escape') {
                setIsOpen(false);
            }
        };

        document.addEventListener('mousedown', onClickOutside);
        document.addEventListener('keydown', onKeyDown);

        return () => {
            document.removeEventListener('mousedown', onClickOutside);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, []);

    if (!resolved) return null;

    return (
        <span className="relative inline-flex" ref={wrapperRef}>
            <button
                type="button"
                ref={triggerRef}
                onClick={() => setIsOpen((prev) => !prev)}
                className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 text-blue-700 hover:bg-blue-200 transition-colors"
                aria-label={`Help for ${resolved.title}`}
                aria-expanded={isOpen}
            >
                <Info className="w-3.5 h-3.5" />
            </button>
            {isOpen && (
                <div
                    ref={setCardRef}
                    className="fixed z-50 w-[min(18rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] bg-gray-900 text-white rounded-lg shadow-2xl px-3 py-2"
                    style={{ top: `${top}px`, left: `${left}px` }}
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
