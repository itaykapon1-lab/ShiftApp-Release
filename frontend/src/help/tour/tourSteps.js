/**
 * @module tour/tourSteps
 * @description Defines the 28-step golden-path interactive tour.
 *
 * Each step object follows this schema:
 *   id            — unique key
 *   phase         — grouping for progress indicator (WELCOME | WORKERS | SHIFTS | CONSTRAINTS | SOLVER)
 *   title         — short heading shown in the TourCard
 *   body          — descriptive paragraph
 *   tip           — optional callout text shown in an indigo box
 *   targetSelector— CSS selector for the element to highlight
 *   targetFinder  — optional () => HTMLElement for dynamic targets
 *   placement     — tooltip placement: top | bottom | left | right | bottom-right
 *   advanceOn     — 'manual' | 'click' | 'action' | 'auto'
 *   advanceCondition — (bridge) => boolean, polled for 'action' type
 *   entryCondition   — (bridge) => boolean, must be true to show step
 *   onEnter       — (bridge) => void, side effect on step entry
 *   onExit        — (bridge) => void, cleanup on step exit
 *   canGoBack     — whether Back button is shown
 *   fallbackStepId — step to revert to if entryCondition fails
 */

/** Helper: find a button by its visible text content. */
const findButtonByText = (text) => {
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
        if (btn.textContent.trim().includes(text)) return btn;
    }
    return null;
};

const tourSteps = [
    // ── PHASE: WELCOME ──────────────────────────────────
    {
        id: 'welcome',
        phase: 'WELCOME',
        title: 'Welcome to ShiftApp!',
        body: 'This guided tour will walk you through the core workflow: adding workers, defining shifts, setting constraints, and running the scheduler. You will perform real actions at each step — everything you create stays in your workspace.',
        tip: 'You can skip the tour at any time. Use "Reset Data" later if you want a fresh start.',
        targetSelector: null,
        placement: 'center',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: false,
    },

    // ── PHASE: WORKERS ──────────────────────────────────
    {
        id: 'workers.tab',
        phase: 'WORKERS',
        title: 'Meet the Workers Tab',
        body: 'This is where you manage employee profiles. Click the Workers tab to get started.',
        tip: null,
        targetSelector: '#tab-workers',
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'workers') bridge.setActiveTab('workers');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'workers.add-btn',
        phase: 'WORKERS',
        title: 'Add Your First Worker',
        body: 'Click the "Add Worker" button to open the worker creation form.',
        tip: null,
        targetSelector: null,
        targetFinder: () => findButtonByText('Add Worker'),
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'workers') bridge.setActiveTab('workers');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'workers.modal-name',
        phase: 'WORKERS',
        title: 'Enter a Worker Name',
        body: 'Type a name for your first worker (e.g. "John Doe") in the highlighted input field. Each worker needs a unique name.',
        tip: 'You can always edit worker details later by clicking their card.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            return modal.querySelector('input[type="text"]');
        },
        placement: 'right',
        advanceOn: 'action',
        advanceCondition: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return false;
            const input = modal.querySelector('input[type="text"]');
            return input && input.value.trim().length > 0;
        },
        entryCondition: (bridge) => bridge.isWorkerModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: false,
        fallbackStepId: 'workers.add-btn',
    },
    {
        id: 'workers.modal-skills',
        phase: 'WORKERS',
        title: 'Define Skills',
        body: 'Skills let the solver match workers to tasks. Type a skill name (e.g. "Chef"), set a proficiency level (1\u201310), then click the + button to add it. A worker can have multiple different skills \u2014 add as many as you need. This section is optional for now.\n\nEligibility Rule: Any worker whose skill level is GREATER THAN OR EQUAL TO (\u2265) the required level can be assigned to that task. For example, a worker with Cooking level 7 satisfies a requirement of Cooking level 5.',
        tip: 'A single Requirement can demand multiple skills from one worker. Only workers who meet ALL required skill levels are eligible.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            return modal.querySelector('.border-indigo-200');
        },
        placement: 'right',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isWorkerModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'workers.add-btn',
    },
    {
        id: 'workers.modal-avail',
        phase: 'WORKERS',
        title: 'Set Availability',
        body: 'Check the days this worker is available and set time ranges. You can also mark preferences (Prefer / Neutral / Avoid). Optional for now.',
        tip: 'The solver respects availability windows — a worker cannot be assigned outside their available hours.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            return modal.querySelector('.border-green-200');
        },
        placement: 'right',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isWorkerModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'workers.add-btn',
    },
    {
        id: 'workers.modal-save',
        phase: 'WORKERS',
        title: 'Save the Worker',
        body: 'Click "Create Worker" to save. The worker will appear in your Workers list.',
        tip: null,
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            const buttons = modal.querySelectorAll('button');
            for (const btn of buttons) {
                if (btn.textContent.includes('Create Worker')) return btn;
            }
            return null;
        },
        placement: 'top',
        advanceOn: 'action',
        advanceCondition: (bridge) => !bridge.isWorkerModalOpen,
        entryCondition: (bridge) => bridge.isWorkerModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'workers.add-btn',
    },
    {
        id: 'workers.done',
        phase: 'WORKERS',
        title: 'Worker Created!',
        body: 'Great job! Your first worker is now in the system. In a real scenario you would add several workers, but one is enough to continue the tour.',
        tip: null,
        targetSelector: null,
        placement: 'center',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: false,
    },

    {
        id: 'workers.excel',
        phase: 'WORKERS',
        title: 'Excel Import / Export',
        body: 'ShiftApp fully supports Excel for managing massive amounts of data:\n\n\u2022 Import Excel — upload Workers, Shifts, and Constraints from a .xlsx spreadsheet in one click. Ideal for large teams with hundreds of employees.\n\u2022 Export State — save your entire workspace (workers, shifts, constraints) to a restorable snapshot.\n\u2022 Export Result — download the generated schedule as a spreadsheet.\n\nThis is the fastest way to onboard an existing roster or share configurations across environments.',
        tip: 'The Excel format supports all fields: worker skills & availability, shift tasks with nested options/requirements, and every constraint type.',
        targetSelector: null,
        targetFinder: () => {
            // Target the action bar containing Import/Export buttons
            const label = document.querySelector('#file-upload-input');
            return label ? label.closest('.flex.gap-3') : null;
        },
        placement: 'bottom',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: true,
    },

    // ── PHASE: SHIFTS ───────────────────────────────────
    {
        id: 'shifts.tab',
        phase: 'SHIFTS',
        title: 'Now Define Shifts',
        body: 'Shifts describe when work needs to happen and what tasks must be covered. Click the Shifts tab.',
        tip: null,
        targetSelector: '#tab-shifts',
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'shifts') bridge.setActiveTab('shifts');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'shifts.add-btn',
        phase: 'SHIFTS',
        title: 'Add a Shift',
        body: 'Click "Add Shift" to open the shift builder.',
        tip: null,
        targetSelector: null,
        targetFinder: () => findButtonByText('Add Shift'),
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'shifts') bridge.setActiveTab('shifts');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'shifts.modal-details',
        phase: 'SHIFTS',
        title: 'Shift Name, Day & Time',
        body: 'Give the shift a descriptive name, pick a day of the week, and set the time range (e.g. 08:00-16:00).',
        tip: 'The day and time define when this shift occurs in the weekly schedule.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            return modal.querySelector('.border-indigo-200');
        },
        placement: 'right',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isShiftModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: false,
        fallbackStepId: 'shifts.add-btn',
    },
    // ── Shift Hierarchy Deep-Dive (multi-step) ────────
    {
        id: 'shifts.modal-tasks-overview',
        phase: 'SHIFTS',
        title: 'The Task Hierarchy — Overview',
        body: 'Shifts use a nested hierarchy to model complex staffing needs:\n\nTask \u2192 Option \u2192 Requirement \u2192 Skill(s)\n\nExample: Task: Front Desk \u2192 Option: Morning Shift \u2192 Requirements: 1 Manager + 2 Receptionists.\n\nLet\u2019s walk through each layer. The blue box below is your first Task — a job that must be staffed during this shift.',
        tip: 'A shift can have multiple Tasks (e.g. "Front Desk" AND "Kitchen"). Each is staffed independently.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            return modal.querySelector('.border-blue-300');
        },
        placement: 'left',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isShiftModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'shifts.add-btn',
    },
    {
        id: 'shifts.modal-options',
        phase: 'SHIFTS',
        title: 'Options — Alternative Staffing Plans',
        body: 'Inside each Task you\u2019ll see Options (the purple area). A single Task can have multiple alternative Options — for example "Morning Crew" OR "Night Crew". The solver picks the best-scoring option automatically.\n\nClick "Add Option" if you want to define an alternative staffing plan. For now, one option is enough.',
        tip: 'Options follow OR logic — only ONE is selected per Task. Use the Priority dropdown (appears with 2+ options) to indicate preference.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            // Target the options container (ml-3/ml-8 under the task)
            return modal.querySelector('.border-purple-300');
        },
        placement: 'left',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isShiftModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'shifts.add-btn',
    },
    {
        id: 'shifts.modal-requirements',
        phase: 'SHIFTS',
        title: 'Requirements — Who You Need',
        body: 'Every Option is built from Requirements (the orange area). Each requirement specifies HOW MANY workers with WHICH skills you need.\n\nYou can add multiple requirements to the same option — for example: "Need 1 Manager AND 2 Cashiers". Click the orange + button to add another requirement.',
        tip: 'Requirements follow AND logic — ALL of them must be satisfied for the option to be valid.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            return modal.querySelector('.border-orange-300');
        },
        placement: 'left',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isShiftModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'shifts.add-btn',
    },
    {
        id: 'shifts.modal-skills',
        phase: 'SHIFTS',
        title: 'Skills — Multi-Skill Requirements',
        body: 'Inside each requirement you can demand MULTIPLE skills from the same worker. Type a skill name, set the minimum level (1\u201310), and click the blue + button to add it.\n\nExample: a single requirement can demand "Manager \u2265 3" AND "First Aid \u2265 1" — only workers who meet ALL listed skills qualify.',
        tip: 'Eligibility Rule: Any worker whose skill level is GREATER THAN OR EQUAL TO (\u2265) the required level can be assigned. The blue + button (or Enter key) confirms each skill.',
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            // Target the skill input row inside the first requirement
            const req = modal.querySelector('.border-orange-300');
            if (!req) return null;
            return req.querySelector('.flex.gap-1') || req;
        },
        placement: 'top',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: (bridge) => bridge.isShiftModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'shifts.add-btn',
    },
    {
        id: 'shifts.modal-save',
        phase: 'SHIFTS',
        title: 'Create the Shift',
        body: 'Click the create button to save this shift.',
        tip: null,
        targetSelector: null,
        targetFinder: () => {
            const modal = document.querySelector('[role="dialog"]');
            if (!modal) return null;
            const buttons = modal.querySelectorAll('button');
            for (const btn of buttons) {
                if (btn.textContent.includes('Create Shift')) return btn;
            }
            return null;
        },
        placement: 'top',
        advanceOn: 'action',
        advanceCondition: (bridge) => !bridge.isShiftModalOpen,
        entryCondition: (bridge) => bridge.isShiftModalOpen,
        onEnter: null,
        onExit: null,
        canGoBack: true,
        fallbackStepId: 'shifts.add-btn',
    },
    {
        id: 'shifts.done',
        phase: 'SHIFTS',
        title: 'Shift Created!',
        body: 'Your shift is ready. With at least one worker and one shift, the solver already has enough data to run. Let\'s look at constraints first.',
        tip: null,
        targetSelector: null,
        placement: 'center',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: false,
    },

    // ── PHASE: CONSTRAINTS ──────────────────────────────
    {
        id: 'constraints.tab',
        phase: 'CONSTRAINTS',
        title: 'Constraints Control the Rules',
        body: 'Constraints tell the solver what it must (or should) respect. Click the Constraints tab.',
        tip: null,
        targetSelector: '#tab-constraints',
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'constraints') bridge.setActiveTab('constraints');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'constraints.hard-soft',
        phase: 'CONSTRAINTS',
        title: 'Hard vs Soft Constraints',
        body: 'When adding a constraint, you choose its strictness:\n\n\u2022 Hard — must be satisfied. Violating even one makes the entire schedule infeasible.\n\u2022 Soft — adds a penalty score when broken, but won\'t block a solution.\n\nSolver Goal: The algorithm\'s primary objective is to find a valid schedule that MINIMIZES the total penalty score across all soft constraints. Lower total penalty = better schedule.',
        tip: 'Start with Soft constraints when experimenting. Switch to Hard once you\'re confident the schedule can satisfy them.',
        targetSelector: '#constraints-add-trigger',
        placement: 'bottom',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'constraints') bridge.setActiveTab('constraints');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'constraints.global',
        phase: 'CONSTRAINTS',
        title: 'Global Settings',
        body: 'Global constraints apply to every worker — like maximum hours per week, minimum rest between shifts, and preference weighting.',
        tip: null,
        targetSelector: null,
        targetFinder: () => {
            const headings = document.querySelectorAll('h3');
            for (const h of headings) {
                if (h.textContent.includes('Global Settings')) return h.closest('.bg-white');
            }
            return null;
        },
        placement: 'right',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'constraints') bridge.setActiveTab('constraints');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'constraints.worker-rules',
        phase: 'CONSTRAINTS',
        title: 'Worker Rules',
        body: 'Worker rules apply to specific worker pairs. Mutual Exclusion prevents two workers from being on the same shift. Co-location forces them together.',
        tip: 'These are useful when certain workers don\'t get along — or when a trainee must always be paired with a mentor.',
        targetSelector: null,
        targetFinder: () => {
            const headings = document.querySelectorAll('h3');
            for (const h of headings) {
                if (h.textContent.includes('Worker Rules')) return h.closest('.bg-white');
            }
            return null;
        },
        placement: 'right',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'constraints') bridge.setActiveTab('constraints');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'constraints.types',
        phase: 'CONSTRAINTS',
        title: 'All Constraint Types',
        body: 'ShiftApp supports five constraint categories:\n\n• Max Weekly Hours — cap total hours per worker\n• Min Rest Between Shifts — enforce minimum recovery time\n• Preference Weight — control how much soft preferences matter\n• Mutual Exclusion — prevent two workers from sharing a shift\n• Co-location — force two workers onto the same shift',
        tip: 'You don\'t need to add any constraints now — the solver works without them. They refine the result.',
        targetSelector: null,
        placement: 'center',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: true,
    },

    // ── PHASE: SOLVER ───────────────────────────────────
    {
        id: 'solver.run',
        phase: 'SOLVER',
        title: 'Run the Solver',
        body: 'Time to generate a schedule! Click "Run Solver" to send your data to the optimization engine. It will satisfy all hard constraints and minimize the total penalty from soft constraints to produce the best possible schedule.',
        tip: 'The solver uses Google OR-Tools milp under the hood — it finds the mathematically optimal assignment that minimizes total penalty.',
        targetSelector: '#btn-run-solver',
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'solver.waiting',
        phase: 'SOLVER',
        title: 'Optimizing...',
        body: 'The solver is crunching numbers. This typically takes a few seconds for small datasets. Larger schedules may take longer.',
        tip: 'The status indicator in the header shows the current job state.',
        targetSelector: null,
        targetFinder: () => document.querySelector('#btn-run-solver'),
        placement: 'bottom',
        advanceOn: 'action',
        advanceCondition: (bridge) => !bridge.isPolling && bridge.solverResult != null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: false,
    },
    {
        id: 'solver.schedule-tab',
        phase: 'SOLVER',
        title: 'View Your Schedule',
        body: 'Results are in! Click the Schedule tab to see your generated assignments.',
        tip: null,
        targetSelector: '#tab-schedule',
        placement: 'bottom',
        advanceOn: 'click',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'schedule') bridge.setActiveTab('schedule');
        },
        onExit: null,
        canGoBack: false,
    },
    {
        id: 'solver.results',
        phase: 'SOLVER',
        title: 'Reading the Results',
        body: 'The schedule grid shows which workers are assigned to which shifts. If the solver found an optimal solution, you\'ll see assignment cards. If it was infeasible, a diagnostics panel explains which constraints conflicted.',
        tip: 'The objective score reflects the total penalty — lower means many soft constraints were broken.',
        targetSelector: null,
        targetFinder: () => {
            // Target the schedule tab content area
            const tabContent = document.querySelector('.p-3.sm\\:p-6.md\\:p-8');
            return tabContent || null;
        },
        placement: 'top',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: (bridge) => {
            if (bridge.activeTab !== 'schedule') bridge.setActiveTab('schedule');
        },
        onExit: null,
        canGoBack: true,
    },
    {
        id: 'solver.complete',
        phase: 'SOLVER',
        title: 'Tour Complete!',
        body: 'You\'ve completed the full workflow — from adding workers and shifts, through constraints, to running the solver. You\'re ready to build real schedules!\n\nNext steps: add more workers, define additional shifts, experiment with constraints, and re-run the solver to see how the schedule changes.',
        tip: 'Use "Export Result" to download the schedule, or "Export State" to save a full snapshot you can restore later.',
        targetSelector: null,
        placement: 'center',
        advanceOn: 'manual',
        advanceCondition: null,
        entryCondition: null,
        onEnter: null,
        onExit: null,
        canGoBack: false,
    },
];

export default tourSteps;
