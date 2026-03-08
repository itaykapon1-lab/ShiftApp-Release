"""Solver result formatting utilities.

This module provides human-readable formatting for solver output,
keeping presentation logic out of the service layer.
"""

from collections import defaultdict
from typing import Any, Dict


def format_solver_results(result: Dict[str, Any]) -> None:
    """Formats solver results in a Tree structure showing specific skills per worker.

    Prints a structured tree view of the weekly schedule to stdout,
    including assignment details, per-task breakdowns, and constraint violations.

    Args:
        result: The solver result dictionary containing 'status', 'statistics',
            'assignments', and 'violations' keys.
    """
    status = result.get("status", "Unknown")
    stats = result.get("statistics", {})
    assignments = result.get("assignments", [])

    print("\n" + "=" * 80)
    print(f"  OPTIMIZATION RESULTS")
    print("=" * 80)
    print(f"   Status: {status.upper()} | Score: {stats.get('objective_value', 0):.2f}")
    print("-" * 80 + "\n")

    if not assignments:
        print("No assignments generated.")
        return

    shifts_map = {}

    for assign in assignments:
        day = assign.get('day', str(assign.get('time', ''))[:10])
        raw_time = assign.get('time', 'N/A')
        time_range = raw_time[11:16] if len(raw_time) > 16 else raw_time
        shift_name = assign.get('shift_name', 'Unknown')

        shift_key = (day, time_range, shift_name)

        if shift_key not in shifts_map:
            shifts_map[shift_key] = {
                'day': day,
                'time': time_range,
                'name': shift_name,
                'tasks': defaultdict(list)
            }

        task_id = assign.get('task', 'General')
        shifts_map[shift_key]['tasks'][task_id].append(assign)

    sorted_shifts = sorted(shifts_map.values(), key=lambda x: (x['day'], x['time']))

    print("  WEEKLY SCHEDULE TREE")
    print("=" * 80)

    for shift in sorted_shifts:
        print(f"  [{shift['day']}] {shift['time']} | {shift['name']}")

        tasks = shift['tasks']
        task_keys = list(tasks.keys())

        for t_idx, task_key in enumerate(task_keys):
            workers = tasks[task_key]
            is_last_task = (t_idx == len(task_keys) - 1)
            task_connector = "  " if is_last_task else "  "
            task_pipe = "    " if is_last_task else "    "

            all_roles_in_task = []
            for w in workers:
                raw = w.get('role_details', '')
                clean = raw.replace('[', '').replace(']', '').replace("'", "").replace('"', '')
                if clean:
                    all_roles_in_task.append(clean)

            display_title = task_key
            if ("Task_" in task_key or "General" in task_key) and all_roles_in_task:
                display_title = " + ".join(sorted(list(set(all_roles_in_task))))

            print(f"{task_connector}  {display_title}")

            for w_idx, w in enumerate(workers):
                worker_name = w.get('worker_name', 'Unknown')
                score = w.get('score', 0)
                score_fmt = f"(+{score})" if score > 0 else f"({score})" if score < 0 else ""

                raw_role = w.get('role_details', '')
                role_clean = raw_role.replace('[', '').replace(']', '').replace("'", "").replace('"', '')
                skill_display = f" {role_clean}" if role_clean else ""

                print(f"{task_pipe}   {worker_name:<15} {score_fmt:<6} {skill_display}")

        print("")

    violations = result.get("violations", {})
    if violations:
        print("=" * 80)
        print("  VIOLATIONS:")
        for rule, v_list in violations.items():
            print(f"    {rule}: {len(v_list)} occurrences")

    print("=" * 80)
