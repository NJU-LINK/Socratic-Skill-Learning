---
name: api-scheduler
description: >
  Build a priority-based schedule from a task list, submit it to a stateful
  calendar API simulator, handle emergencies via replanning, and produce
  output.json + history.jsonl. Covers urgency/eisenhower/weighted scoring,
  dependency DAGs, hard deadlines, transient-error retry, and batch insertion.
---

# API Scheduler Skill

## Overview

You are a product manager with a fixed work window. Tasks live in
`/app/tasks.json`. You must schedule them by priority into a calendar API
simulator at `/app/api_simulator.py`, handle any emergencies that arrive, and
produce `/app/output.json` and `/app/history.jsonl`.

## Step-by-Step Procedure

### 1. Read All Inputs

Read these files from `/app/`:

- **`tasks.json`** — Contains `tasks` (list), `emergencies` (list, possibly empty),
  and `config` with `work_start`, `work_end`, `priority_method`, `calendar_id`.
- **`simulator_intro.md`** — The scheduling contract (priority rules, replanning
  protocol, output format). Always read this; it is the authoritative spec.
- **`api_simulator.py`** — The concrete API implementation. Inspect it to discover
  which commands are supported (especially `batch_insert`).

### 2. Compute Priority Scores

For each task, compute a score based on `config.priority_method`:

| Method | Formula |
|---|---|
| `urgency` | `score = urgency` |
| `eisenhower` | `score = urgency × importance` |
| `weighted` (no `team_priority`) | `score = 0.6×urgency + 0.4×importance` |
| `weighted` (with `team_priority`) | `score = 0.5×urgency + 0.3×importance + 0.2×team_priority` |

**Tie-breaking** (applied in order until the tie is broken):
1. Higher score first.
2. Earlier hard `deadline` first. A task **without** a deadline sorts **after**
   a task **with** one.
3. Original order in `tasks.json` (input order, 0-indexed).

### 3. Build the Initial Schedule (Greedy Algorithm)

```
current_time = config.work_start  (in minutes from midnight)
end_limit = config.work_end       (in minutes from midnight)
remaining = all normal tasks
scheduled = []   # list of events
missed = []      # list of task_ids
completed_ids = set()  # task_ids placed in schedule

while remaining is not empty:
    # Find highest-priority task whose dependencies are satisfied
    chosen = None
    for task in remaining (in priority order):
        deps = task.get("depends_on", [])
        if all(d in completed_ids for d in deps):
            chosen = task
            break

    if chosen is None:
        # No task has satisfiable deps — all remaining are blocked → missed
        for task in remaining:
            missed.append(task["id"])
        break

    dur = chosen["duration_min"]
    end_time = current_time + dur
    deadline = chosen.get("deadline")

    fits = (end_time <= end_limit)
    if deadline is not None:
        fits = fits and (end_time <= to_minutes(deadline))

    if fits:
        schedule event:
          task_id = chosen["id"]
          title = chosen["title"]
          start = to_time(current_time)
          end = to_time(end_time)
          status = "scheduled"
        current_time = end_time
        completed_ids.add(chosen["id"])
    else:
        missed.append(chosen["id"])
        # Do NOT add to completed_ids → dependents will also be missed

    remove chosen from remaining
```

**Key rules:**
- Events are uninterrupted and non-overlapping.
- A task that cannot finish by its hard deadline or by `work_end` is **missed**.
- If a prerequisite is missed, all tasks that (transitively) depend on it are
  also missed (they will never find their deps satisfied).
- Build the plan **without** reserving time for future emergencies.

### 4. Submit Initial Plan to the API

**The first mutation must always be `clear`.**

#### Interaction pattern
The simulator reads one JSON command per line from stdin and writes one JSON
response per line to stdout. You can batch multiple commands in one invocation:

```bash
printf '%s\n' \
  '{"cmd":"clear","calendar_id":"<ID>"}' \
  '{"cmd":"insert","calendar_id":"<ID>","event":{...}}' \
  '{"cmd":"list","calendar_id":"<ID>"}' \
  | python3 /app/api_simulator.py
```

Each stdout line corresponds to one command's response, in order.

#### Basic mode (individual inserts):
After `clear`, insert each event one by one.

#### Batch mode:
Inspect `api_simulator.py`. If it defines a `batch_insert` handler, submit the
initial plan in one call:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[{event1},{event2},...]}
```

### 5. Handle Emergencies (Replanning Protocol)

Process emergencies sorted by `arrival_time` (chronological order).

For **each** emergency:

1. **Identify preserved events**: Calendar events whose `end ≤ arrival_time`
   stay. These tasks remain completed.

2. **Delete future/overlapping events**: Every event whose `end > arrival_time`
   must be deleted (including any event in progress at arrival time).
   - Use `list` to get current events and their `event_id`s.
   - Use `delete` with each `event_id` to remove.
   - The corresponding tasks return to the remaining-task pool at **full
     duration** (no partial credit for interrupted work).

   **Rebuild state from the calendar after deletion:**
   ```
   completed_ids = {task_id for each preserved event in the calendar}
   remaining = all normal tasks whose task_id is NOT in completed_ids
   ```
   This ensures the replanning loop is self-contained: derive what is done
   from the actual calendar state, not from stale in-memory variables.

3. **Insert the emergency event**: Schedule at exactly `arrival_time`.
   - `start` = arrival_time
   - `end` = arrival_time + emergency.duration_min
   - Must finish by its deadline (if present) and by `work_end`.
   - Status = `"emergency"`.

   **If the emergency cannot fit** (end > work_end, or end > its deadline):
   - Do **NOT** insert the emergency into the calendar.
   - The emergency is not added to completed_ids.
   - Proceed directly to rebuilding the remaining normal plan starting at
     `arrival_time` (not the emergency's end, since it was never inserted).
   - Log the decision for debugging.

4. **Rebuild remaining normal plan**:
   - If the emergency was inserted: start at the emergency's `end` time.
   - If the emergency could not fit: start at `arrival_time`.
   - Schedule remaining normal tasks using the same greedy priority/dependency
     rules from Step 3. Events created during replanning get status
     `"rescheduled"`.
   - As each rescheduled task is placed, add its task_id to completed_ids.
   - Tasks that are marked missed during rebuild do **NOT** enter
     completed_ids, so their dependents will also be missed (same cascade
     as the initial plan).

5. **Update state**: If the emergency was inserted, add its task_id to
   completed_ids. Rescheduled tasks were already added during Step 4.

Repeat for each subsequent emergency. The final calendar state must be
chronological and non-overlapping.

### 6. Handle Transient Errors

If the API returns `{"status": "error", ...}`:
- **Retry the same logical operation** until it succeeds.
- Record **every attempt** (including failed ones) in `history.jsonl`.
- Common transient errors: `"Rate limit exceeded"`, `"Internal server error"`.

### 7. Record History

Write `/app/history.jsonl` — one JSON object per line for **every** API
request/response pair, in chronological order:

```json
{"request": {"cmd": "clear", "calendar_id": "..."}, "response": {"status": "ok", ...}}
{"request": {"cmd": "insert", ...}, "response": {"status": "ok", "event_id": "evt_0"}}
{"request": {"cmd": "insert", ...}, "response": {"status": "error", "message": "..."}}
{"request": {"cmd": "insert", ...}, "response": {"status": "ok", "event_id": "evt_1"}}
```

Include retries and errors.

### 8. Write Output

Write `/app/output.json`:

```json
{
  "schedule": [
    {
      "task_id": "A",
      "title": "Review Q3 Report",
      "start": "14:00",
      "end": "15:00",
      "status": "scheduled"
    }
  ],
  "completion_summary": {
    "completed": ["A", "B"],
    "missed": ["C"],
    "total_tasks": 3,
    "completed_count": 2,
    "missed_count": 1
  }
}
```

**Status values:**
- `"scheduled"` — normal events from the initial plan.
- `"rescheduled"` — normal events placed after an emergency replan.
- `"emergency"` — emergency events.

**completion_summary fields:**
- `completed` — task_ids that appear in the final schedule (any status).
- `missed` — task_ids that could not be scheduled.
- `total_tasks` — count of all normal tasks (not counting emergencies).
- `completed_count` — `len(completed)`.
- `missed_count` — `len(missed)`.

The schedule array must be in chronological order.

### 9. Verify Final State

After writing output.json, perform an explicit verification:

1. Send `{"cmd":"list", "calendar_id":"<ID>"}` to the simulator.
2. Record the response in history.jsonl.
3. Compare the list response against output.json's schedule array:
   - The number of events in the list response must equal `len(schedule)`.
   - Each event's `task_id`, `title`, `start`, `end` must match a
     corresponding entry in output.json's schedule array.
4. If **any** mismatch is found, fix it:
   - a. If an event is in output.json but **not** in the calendar → insert it.
   - b. If an event is in the calendar but **not** in output.json → delete it.
   - c. Re-list to confirm the fix.
5. Only proceed once the calendar state and output.json are consistent.

This step is the safety net against partial deletions during emergency
replanning, failed inserts that weren't retried, or silent batch-insert
failures. It turns Invariant #2 from a hope into a check.

## Critical Invariants

1. **First mutation is always `clear`.**
2. **Final simulator state must exactly match `output.json`.**
3. **All events are non-overlapping and chronological.**
4. **Every event has `task_id`, `title`, `start`, `end`.**
5. **Times are `HH:MM` format.**
6. **`calendar_id` comes from `tasks.json` config.**
7. **Record every API interaction in history.jsonl, including errors and retries.**
8. **Distinct task_ids remain distinct even when titles are duplicated.**

## Time Arithmetic

```python
def to_minutes(t: str) -> int:
    """Convert 'HH:MM' to minutes from midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def to_time(minutes: int) -> str:
    """Convert minutes from midnight to 'HH:MM'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
```

## Variant-Specific Notes

### Dependency DAGs
Tasks may have a `depends_on` field listing prerequisite task IDs. A task can
only be scheduled after all its prerequisites appear earlier in the plan. If a
prerequisite is missed, all tasks that (transitively) depend on it are also
missed — they will never find their deps satisfied in the greedy loop.

### Hard Deadlines
Tasks may have a `deadline` field (e.g., `"16:00"`). The task must **finish**
by this time or it is missed. In priority tie-breaking, earlier deadlines sort
first; tasks with no deadline sort after tasks with one.

### Duplicate Titles
Multiple tasks may share the same `title` but have distinct `task_id` values.
Always identify events by `task_id`, not title.

### Infeasible Tasks
If a task's duration exceeds the available window, or its deadline is before
`work_start + duration`, it will be missed. This is expected and correct.

### Batch Insert
When `api_capability` is `batch`, inspect `api_simulator.py` for a
`batch_insert` command. Use it to submit the initial plan in one call:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[{...},{...}]}
```
After batch_insert, verify with `list` to confirm all events are present.

### Transient Errors
When `api_capability` is `transient-errors`, the simulator may randomly return
error responses. Retry the same operation until it succeeds. Record all
attempts in history.

## Worked Example (v01 anchor)

**Input:** 5 tasks, urgency scoring, no emergencies, 14:00–19:00.

**Priority order** (by urgency desc, then input order for ties):
1. A (urgency=5, 60min) → 14:00–15:00
2. B (urgency=4, 45min) → 15:00–15:45
3. D (urgency=3, 40min) → 15:45–16:25
4. C (urgency=2, 30min) → 16:25–16:55
5. E (urgency=1, 35min) → 16:55–17:30

Total: 210 min. All fit within 300-min window. No emergencies.
Result: 5 completed, 0 missed.
