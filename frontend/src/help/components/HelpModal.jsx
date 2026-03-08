import React from 'react';
import { BookOpen, Lightbulb, AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import Modal from '../../components/common/Modal';

const calloutStyles = {
    info: 'bg-blue-50 border-blue-200 text-blue-900',
    tip: 'bg-indigo-50 border-indigo-200 text-indigo-900',
    warning: 'bg-amber-50 border-amber-300 text-amber-900',
    success: 'bg-emerald-50 border-emerald-200 text-emerald-900',
};

const calloutIcons = {
    info: Info,
    tip: Lightbulb,
    warning: AlertTriangle,
    success: CheckCircle2,
};

const HelpModal = ({ isOpen, onClose, topic, getGlossaryTerm }) => {
    if (!topic) {
        return (
            <Modal isOpen={isOpen} onClose={onClose} title="Help" size="xl">
                <p className="text-gray-700">No help content is available for this section yet.</p>
            </Modal>
        );
    }

    return (
        <Modal isOpen={isOpen} onClose={onClose} title={topic.title} size="xl">
            <div className="space-y-6">
                <div className="bg-gradient-to-r from-indigo-50 to-blue-50 border-2 border-indigo-200 rounded-xl p-4">
                    <p className="text-sm text-indigo-900">
                        <strong>Audience:</strong> {topic.audience}
                    </p>
                </div>

                <div className="space-y-4">
                    {(topic.sections || []).map((section) => {
                        const calloutType = section.calloutType || 'info';
                        const style = calloutStyles[calloutType] || calloutStyles.info;
                        const Icon = calloutIcons[calloutType] || calloutIcons.info;

                        return (
                            <section key={section.id} className={`border rounded-xl p-4 ${style}`}>
                                <h3 className="font-bold text-base flex items-center gap-2 mb-2">
                                    <Icon className="w-4 h-4" />
                                    {section.heading}
                                </h3>
                                <p className="text-sm leading-6">{section.body}</p>
                            </section>
                        );
                    })}
                </div>

                {Array.isArray(topic.relatedActions) && topic.relatedActions.length > 0 && (
                    <div className="border-2 border-gray-200 rounded-xl p-4">
                        <h4 className="font-bold text-gray-800 mb-3">Related Actions</h4>
                        <div className="flex flex-wrap gap-2">
                            {topic.relatedActions.map((action) => (
                                <span
                                    key={action}
                                    className="px-2.5 py-1 rounded-lg bg-gray-100 border border-gray-200 text-sm font-medium text-gray-700"
                                >
                                    {action}
                                </span>
                            ))}
                        </div>
                    </div>
                )}

                {Array.isArray(topic.glossaryTerms) && topic.glossaryTerms.length > 0 && (
                    <div className="border-2 border-gray-200 rounded-xl p-4">
                        <h4 className="font-bold text-gray-800 mb-3 flex items-center gap-2">
                            <BookOpen className="w-4 h-4" />
                            Key Terms
                        </h4>
                        <div className="space-y-2">
                            {topic.glossaryTerms.map((termId) => {
                                const term = getGlossaryTerm(termId);
                                if (!term) return null;

                                return (
                                    <div key={term.id} className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                                        <div className="font-semibold text-gray-800 text-sm">{term.title}</div>
                                        <div className="text-sm text-gray-600 mt-1">{term.content}</div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        </Modal>
    );
};

export default HelpModal;
