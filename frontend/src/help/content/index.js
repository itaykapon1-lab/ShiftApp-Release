import topicsData from './topics.json';
import glossaryData from './glossary.json';
import onboardingData from './onboarding.json';

const topicMap = new Map((topicsData.topics || []).map((topic) => [topic.id, topic]));
const glossaryMap = new Map((glossaryData.terms || []).map((term) => [term.id, term]));

export const HELP_CONTENT_VERSION = topicsData.version || '1.0';
export const helpTopics = topicsData.topics || [];
export const glossaryTerms = glossaryData.terms || [];
export const onboardingConfig = onboardingData;

export const getTopicById = (topicId) => topicMap.get(topicId) || null;
export const getGlossaryTermById = (termId) => glossaryMap.get(termId) || null;

