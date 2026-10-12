---
name: api-scheduler
description: >
  Build a priority-based schedule from tasks.json, submit it to a stateful
  calendar API simulator, and revise remote state when emergencies invalidate
  the plan. Covers urgency/eisenhower/weighted scoring, dependency DAGs,
  hard deadlines, work windows, transient-error retries, batch insertion,
  and emergency replanning with correct status tracking.
---

# API Scheduler Skill

## Overview

You are given `/app/tasks.json` (tasks, emergencies, config) and a stateful
calendar API simulator at `/app/api_simulator.py`. You must:

1. Compute a deterministic priority schedule.
2. Submit it to the simulator via JSON-line commands on stdin.
3. Handle any emergencies by deleting invalidated events and rebuilding.
4. Write `/app/output.json` (final schedule + completion summary) and
   `/app/history.jsonl` (every API request/response pair).

The canonical solver script lives at `scripts/solve.py` in this skill package.
Copy it into the task container and run it:

```bash
cat > /app/solve.py << 'PYEOF'
<paste contents of scripts/solve.py>
PYEOF
python3 /app/solve.py
```

## Inputs

`/app/tasks.json` structure:

```json
{
  "tasks": [
    {"id": "A", "title": "...", "duration_min": 60,
     "urgency": 5, "importance": 3,
     "deadline": "16:00", "depends_on": ["B"]}
  ],
  "emergencies": [
    {"id": "E1", "title": "...", "arrival_time": "15:30",
     "duration_min": 30, "deadline": "16:00"}
  ],
  "config": {
    "work_start": "14:00",
    "work_end": "19:00",
    "priority_method": "urgency",
    "calendar_id": "..."
  }
}
```

Fields `deadline`, `depends_on`, and `team_priority` are optional and may be
absent. `emergencies` may be an empty array.

## Priority Scoring (family invariant)

The `priority_method` in config determines the score:

| Method       | Formula                                        |
|--------------|------------------------------------------------|
| `urgency`    | `score = u`                                    |
| `eisenhower` | `score = u * i`                                |
| `weighted`   | `0.6*u + 0.4*i` (or `0.5*u + 0.3*i + 0.2*t` when `team_priority` present) |

**Tie-breaking** (applied in order):
1. Higher score first.
2. Earlier hard deadline first; a task **without** a deadline sorts **after** any task with one.
3. Input order in `tasks.json` (original array index).

Distinct task IDs remain distinct even when titles are identical.

## Scheduling Algorithm

### Initial Plan

Build without reserving time for future emergencies:

1. Start clock at `config.work_start`.
2. Maintain sets: `completed_ids` (scheduled so far), `missed_ids`.
3. Sort remaining tasks by the priority key above.
4. For each task in priority order:
   - If any `depends_on` task is in `missed_ids` → mark this task missed (cascade).
   - If any `depends_on` task is not yet in `completed_ids` → defer to next round.
   - If `current_time + duration > work_end` → missed.
   - If task has a `deadline` and `current_time + duration > deadline` → missed.
   - Otherwise: schedule at `[current_time, current_time + duration]`, add to
     `completed_ids`, advance clock.
5. Repeat rounds until no progress. If remaining tasks have unresolvable
   dependencies, mark them all missed.

### Emergency Replanning

Process emergencies in chronological `arrival_time` order. For each:

1. **List** current calendar events.
2. **Preserve** events whose `end <= arrival_time` (mark their task_ids as completed).
3. **Delete** every event whose `end > arrival_time` (including in-progress).
   Interrupted normal work gets no partial credit; those task_ids return to
   the remaining pool at full duration.
4. **Insert** the emergency at exactly `arrival_time` for its duration.
   It must finish by its deadline (if any) and by `work_end`.
5. **Rebuild** the remaining normal-task plan starting at the emergency's end
   time, using the same dependency and priority rules.

Repeat for subsequent emergencies.

### Status Labels

| Context                  | `status` value |
|--------------------------|----------------|
| Initial plan events      | `"scheduled"`  |
| Post-emergency normal    | `"rescheduled"`|
| Emergency events         | `"emergency"`  |

## API Interaction Protocol

### Commands

```json
{"cmd":"clear","calendar_id":"..."}
{"cmd":"insert","calendar_id":"...","event":{"task_id":"A","title":"...","start":"14:00","end":"15:00"}}
{"cmd":"list","calendar_id":"..."}
{"cmd":"get","calendar_id":"...","event_id":"evt_0"}
{"cmd":"delete","calendar_id":"...","event_id":"evt_0"}
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

### Critical Rules

1. **First mutation must be `clear`** — the simulator persists state; always reset.
2. **Include `status` in every inserted event** — the test compares simulator state
   (after stripping the remote `id` field) to `output.json`'s schedule. If `status`
   is only in the output but not in the simulator events, they won't match. Always
   include `"status": "scheduled"` / `"rescheduled"` / `"emergency"` in the event
   dict when inserting.
3. **Detect `batch_insert`** by inspecting `api_simulator.py` source for the string
   `"batch_insert"`. If present, submit the initial plan as a single batch.
   Fall back to individual inserts if batch fails.
4. **Retry transient errors** — messages containing "rate limit", "internal server
   error", or "try again" are transient. Retry the same logical operation up to
   10 times.
5. **Log every attempt** — every request/response pair (including errors) goes to
   `history.jsonl` as `{"request": {...}, "response": {...}}`.
6. **Verify with `list`** — after all mutations, call `list` and confirm the
   simulator state exactly matches `output.json`'s schedule.

## Output Format

`/app/output.json`:

```json
{
  "schedule": [
    {"task_id": "A", "title": "...", "start": "14:00", "end": "15:00", "status": "scheduled"}
  ],
  "completion_summary": {
    "completed": ["A"],
    "missed": ["B"],
    "total_tasks": 2,
    "completed_count": 1,
    "missed_count": 1
  }
}
```

- `schedule` entries are chronological and non-overlapping.
- `completed` and `missed` contain only normal task IDs (not emergency IDs).
- `completed` and `missed` must be **sorted alphabetically** (not in schedule order).
- `total_tasks` = count of normal tasks.

## Common Pitfalls

1. **Workspace boundary**: The skill workspace is not mounted inside the
   container. Use a heredoc (`cat > /app/solve.py << 'PYEOF'`) to copy the
   script into `/app/`.
2. **State persistence**: The simulator uses a state file (`/tmp/calendar_state.json`).
   Always `clear` first, even if the container seems fresh.
3. **History must include errors**: The test checks `history.jsonl` for completeness.
   Every `call_api` invocation writes to history, including failed attempts.
4. **Dependency cascade**: If task B depends on A and A is missed, B is also missed.
   The algorithm handles this by checking `deps_possible` before `deps_met`.
5. **Deadline tie-breaking**: A task with deadline "16:00" sorts before a task
   with no deadline, even if the no-deadline task has a higher score. This is
   implemented as `has_deadline = 0` (with deadline) vs `1` (without).
6. **Emergency interrupts in-progress work**: An event with `start < arrival < end`
   is deleted entirely. The task returns to the pool at full duration.
7. **Multiple emergencies**: Each emergency triggers a full replan cycle.
   Events preserved from earlier emergencies remain preserved.
8. **Status field must be in simulator state**: The test `test_final_calendar_state_matches_output`
   strips the remote `id` from simulator events and compares them to `output.json`'s schedule.
   If you insert events without `status`, the simulator won't store it, and the comparison
   will fail. Always include `status` in the event dict when calling `insert` or `batch_insert`.
9. **`completed` and `missed` must be sorted**: The tests compare `completion_summary.completed`
   to `sorted(expected_ids)` and `sorted(scheduled_ids)`. Always sort these lists alphabetically,
   not in schedule order.

## Verification Checklist

Before declaring success, confirm:

- [ ] `history.jsonl` starts with a `clear` command.
- [ ] Every API call (including retries and errors) is logged.
- [ ] Every inserted event includes `status` field (scheduled/rescheduled/emergency).
- [ ] `output.json` schedule matches the final `list` response exactly (after stripping `id`).
- [ ] Events are chronological and non-overlapping.
- [ ] Status labels are correct (`scheduled` / `rescheduled` / `emergency`).
- [ ] `completion_summary` counts match the schedule.
- [ ] `completed` and `missed` lists are sorted alphabetically.
- [ ] Missed tasks include cascaded dependency failures.
- [ ] Simulator state fields match output schedule fields (both have `status`).
