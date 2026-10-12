---
name: api-scheduler
description: >
  Build a priority-based schedule using a stateful calendar API simulator,
  then revise it when emergencies invalidate the plan. Handles urgency,
  eisenhower, and weighted priority methods; dependency DAGs with missed-task
  cascading; emergency replanning with partial-progress invalidation;
  transient API errors with retry; and optional batch insertion.
---

# API Scheduler Skill

## Overview

You are a product manager who must schedule tasks into a work window using a
stateful calendar API. Tasks have priorities, durations, optional deadlines,
and optional dependencies. Emergencies may arrive mid-day, invalidating
overlapping and future calendar entries. You must interact with the API
simulator, record every request/response, and produce a final schedule.

## Input

Read `/app/tasks.json`:
```json
{
  "tasks": [
    {"id": "A", "title": "...", "duration_min": 60, "urgency": 5, "importance": 3,
     "deadline": "16:00", "depends_on": ["B"], "team_priority": 2}
  ],
  "emergencies": [
    {"id": "EM1", "title": "...", "arrival_time": "15:30", "duration_min": 30}
  ],
  "config": {
    "work_start": "14:00",
    "work_end": "19:00",
    "priority_method": "urgency",
    "calendar_id": "Hk9Nw8KsRd5X"
  }
}
```

## API Simulator

The simulator at `/app/api_simulator.py` reads JSON commands from stdin, one
per line, and writes JSON responses to stdout. State persists across
invocations via a temp file.

### Supported commands

| Command | Fields | Description |
|---------|--------|-------------|
| `clear` | `calendar_id` | Reset calendar to empty state. **Must be first mutating call.** |
| `insert` | `calendar_id`, `event` | Add event with `task_id`, `title`, `start`, `end`. Returns `event_id`. |
| `list` | `calendar_id` | Return all events. |
| `get` | `calendar_id`, `event_id` | Return single event. |
| `delete` | `calendar_id`, `event_id` | Remove event. |
| `batch_insert` | `calendar_id`, `events` | Insert multiple events at once. **Only if supported** — inspect `api_simulator.py` for `batch_insert`. |

### Response format

```json
{"status": "ok", ...}      // success
{"status": "error", "message": "..."}  // failure
```

### Transient errors

Some variants inject random errors (rate limits, internal server errors).
**Retry the same logical operation until it succeeds.** Record every attempt
(including failures) in `history.jsonl`.

## Priority Scoring

Compute a score for each task based on `config.priority_method`:

| Method | Formula |
|--------|---------|
| `urgency` | `score = urgency` |
| `eisenhower` | `score = urgency * importance` |
| `weighted` (no team_priority) | `score = 0.6*urgency + 0.4*importance` |
| `weighted` (with team_priority) | `score = 0.5*urgency + 0.3*importance + 0.2*team_priority` |

**Higher scores come first.**

### Tie-breaking

1. Earlier hard deadline first.
2. Task without deadline sorts **after** task with deadline.
3. Input order in `tasks.json` (original array index).

## Scheduling Algorithm

### Initial plan

1. Start at `config.work_start`.
2. Repeatedly choose the **highest-priority remaining task** whose
   `depends_on` tasks have already been scheduled or completed.
3. Schedule it at the next free minute **only if** it finishes by:
   - Its hard deadline (when present), AND
   - `config.work_end`
4. If it doesn't fit, mark it **missed** and continue to the next task.
5. **Cascade**: If a prerequisite is missed, all tasks that depend on it
   are also missed (recursively).

### Submit to API

- If `batch_insert` is supported (inspect `api_simulator.py`), submit the
  entire initial plan in one call.
- Otherwise, insert events one by one in schedule order.
- Record every API call in `history.jsonl`.

### Emergency replanning

Process emergencies in **chronological `arrival_time` order**. At each arrival:

1. **Preserve** calendar events whose `end <= arrival_time`.
2. **Delete** every event whose `end > arrival_time` (including mid-progress).
   - Interrupted normal work receives **no partial credit** and returns to
     the remaining-task pool at **full duration**.
3. **Insert** the emergency at exactly its `arrival_time`. It must finish by
   its deadline (when present) and by `work_end`.
4. **Rebuild** the remaining normal plan starting at the emergency's end time,
   using the same dependency and priority rules.
5. Events created after an emergency use status `"rescheduled"`.

Repeat for each subsequent emergency.

### Status labels

Each schedule event must include a `status` field:

| Context | Status value |
|---------|-------------|
| Initial plan | `"scheduled"` |
| After emergency | `"rescheduled"` |
| Emergency event | `"emergency"` |

**Include `status` in the API insert events** — the simulator stores all fields, so the remote calendar state will also have `status`. This ensures `output.json` matches the remote state after `strip_remote_id` removes the internal `id` field.

## Output

Write `/app/output.json`:
```json
{
  "schedule": [
    {
      "task_id": "A",
      "title": "...",
      "start": "14:00",
      "end": "15:00",
      "status": "scheduled"
    }
  ],
  "completion_summary": {
    "completed": ["A", "B", "D"],
    "missed": ["C", "E"],
    "total_tasks": 5,
    "completed_count": 3,
    "missed_count": 2
  }
}
```

**Important**: 
- Both `completed` and `missed` lists must be **sorted alphabetically** by task ID.
- Each schedule event must have **exactly** these 5 keys: `task_id`, `title`, `start`, `end`, `status`.
- **Include `status` in the API insert events** — the simulator stores all fields, so the remote state will also have `status`, making output match remote state.

Write `/app/history.jsonl` with one JSON object per line:
```json
{"request": {...}, "response": {...}}
```

**Note**: Schedule events in `output.json` MUST include a `status` field. The simulator stores all fields sent in the insert, so include `status` when inserting events. After `strip_remote_id` removes the internal `id` field, the remote state will match the output exactly.

## Execution

The skill package includes a ready-to-run solver at `scripts/solve.py`. Since the skill package is mounted read-only and the agent workspace is separate, you must copy the solver content into `/app/solve.py` before running it.

**Option 1: Copy from skill package (if accessible)**
```bash
cp /skill/api-scheduler/scripts/solve.py /app/solve.py
rm -f /tmp/calendar_state.json
python3 /app/solve.py
```

**Option 2: Write the solver inline**
If the skill package path is not accessible, implement the solver directly following the Procedure section above. The solver must:
- Read `/app/tasks.json`
- Compute priority scores using the formulas in "Priority Scoring"
- Build a greedy schedule respecting dependencies and deadlines
- Clear the calendar first, then insert events
- Handle emergencies by deleting future events and rebuilding
- Include at least one `list` API call in history
- Write `/app/output.json` with schedule events including `status` field and sorted `completed`/`missed` lists
- Write `/app/history.jsonl` with all API requests/responses

## Procedure

1. **Read** `/app/tasks.json` and `/app/simulator_intro.md`.
2. **Inspect** `/app/api_simulator.py` to detect `batch_insert` support.
3. **Clear** the calendar (first mutating call).
4. **Compute** priority scores for all tasks.
5. **Build** the initial schedule using the greedy algorithm.
6. **Submit** the initial plan to the API (batch or individual inserts).
7. **Process** emergencies in chronological order:
   - Delete overlapping/future events
   - Insert emergency
   - Rebuild remaining schedule
8. **List** the final calendar state (required for verification).
9. **Write** `/app/output.json` and `/app/history.jsonl`.

## Common pitfalls

- **Ordering**: `completed` and `missed` must be **sorted alphabetically**, not in schedule order.
- **Status field**: Schedule events MUST include `status` (`"scheduled"`, `"rescheduled"`, or `"emergency"`). Include `status` in API insert events so remote state matches output.
- **Event keys**: Each schedule event must have exactly 5 keys: `task_id`, `title`, `start`, `end`, `status`.
- **List call**: Must include at least one successful `list` API call in history for verification.
- **Dependencies**: If task B depends on A and A is missed, B is also missed.
- **Partial progress**: Interrupted tasks return at full duration, not remaining time.
- **Deadline check**: Task must finish **by** deadline, not start by deadline.
- **No-deadline tie-break**: Tasks without deadlines sort **after** tasks with deadlines.
- **Transient errors**: Retry until success; record every attempt.
- **Batch support**: Only use `batch_insert` if the simulator explicitly supports it.

## Example: v01

Given 5 tasks with urgency scores [5, 4, 2, 3, 1], work window 14:00–19:00,
no emergencies, no dependencies:

**Priority order**: A(5) → B(4) → D(3) → C(2) → E(1)

**Schedule**:
- A: 14:00–15:00
- B: 15:00–15:45
- D: 15:45–16:25
- C: 16:25–16:55
- E: 16:55–17:30

All tasks fit (210 min < 300 min available). Completed: [A, B, C, D, E] (sorted alphabetically).
