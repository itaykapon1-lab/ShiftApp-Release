import { describe, expect, it } from 'vitest';

import { mergeGlobalViolations } from '../components/tabs/ScheduleTab';


describe('ScheduleTab violation mapping', () => {
    const workers = [
        { worker_id: 'W_A', name: 'Alice' },
        { worker_id: 'W_B', name: 'Bob' },
        { worker_id: 'W_C', name: 'Charlie' },
    ];

    const assignments = [
        { worker_id: 'W_A', worker_name: 'Alice', shift_id: 'S_1', shift_name: 'Morning', score: 0 },
        { worker_id: 'W_B', worker_name: 'Bob', shift_id: 'S_1', shift_name: 'Morning', score: 0 },
        { worker_id: 'W_C', worker_name: 'Charlie', shift_id: 'S_2', shift_name: 'Evening', score: 0 },
    ];

    it('maps metadata-driven pair violations to exact assignments', () => {
        const penaltyBreakdown = {
            ban_W_A_W_B: {
                total_penalty: -100,
                violation_count: 1,
                violations: [
                    {
                        description: 'Worker Alice and Worker Bob were assigned together in shift Morning.',
                        penalty: -100,
                        metadata: {
                            rule_type: 'mutual_exclusion',
                            worker_ids: ['W_A', 'W_B'],
                            worker_names: ['Alice', 'Bob'],
                            shift_id: 'S_1',
                            shift_name: 'Morning',
                        },
                    },
                ],
            },
        };

        const merged = mergeGlobalViolations(assignments, penaltyBreakdown, workers);

        expect(merged[0].global_violations).toHaveLength(1);
        expect(merged[1].global_violations).toHaveLength(1);
        expect(merged[2].global_violations).toHaveLength(0);
        expect(merged[0].global_violations[0].description).toContain('assigned together');
    });

    it('does not attach violations to cards when no mapping hints are available', () => {
        const penaltyBreakdown = {
            unknown_rule: {
                total_penalty: -25,
                violation_count: 1,
                violations: [
                    {
                        description: 'Unparseable violation text',
                        penalty: -25,
                    },
                ],
            },
        };

        const merged = mergeGlobalViolations(assignments, penaltyBreakdown, workers);
        merged.forEach((assignment) => {
            expect(assignment.global_violations).toHaveLength(0);
        });
    });
});
