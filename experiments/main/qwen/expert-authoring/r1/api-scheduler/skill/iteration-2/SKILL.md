---
name: api-scheduler
description: >
  Schedule tasks via a stateful calendar API using deterministic priority
  scoring, handle chronological emergencies with stateful replanning, and
  produce matching API history and output artifacts.
---

# API Scheduler

## Overview

You are a product manager who must schedule tasks into a calendar using a
stateful API simulator. The workflow is:

1. Read inputs (`tasks.json`, `simulator_intro.md`)
2. Compute deterministic priorities
3. Build an initial schedule respecting work window, deadlines, and dependencies
4. Submit the schedule to the calendar API (clear → insert/batch_insert)
5. Process emergencies chronologically (delete future events, insert emergency,
   reschedule remaining)
6. Write `history.jsonl` (every API attempt) and `output.json` (final schedule)

**Critical**: The final simulator state must exactly match `output.json`. The
test compares calendar events (minus `id`) field-by-field against the
`output.json` schedule array. Every field in `output.json` — including
`status` — **must also be stored in the calendar** via the insert event
payload. The simulator stores the entire event dict verbatim, so include
`status` in every `insert` / `batch_insert` call.

---

## Step 1 — Read Inputs

### tasks.json structure

```json
{
  "tasks": [
    {
      "id": "A",
      "title": "...",
      "duration_min": 60,
      "urgency": 5,
      "importance": 3,
      "team_priority": 2,       // optional
      "hard_deadline": "16:00", // optional, HH:MM
      "depends_on": ["B"]       // optional, list of task IDs
    }
  ],
  "emergencies": [
    {
      "id": "E1",
      "title": "...",
      "duration_min": 30,
      "arrival_time": "15:30",
      "hard_deadline": "17:00"  // optional
    }
  ],
  "config": {
    "work_start": "14:00",
    "work_end": "19:00",
    "priority_method": "urgency",
    "calendar_id": "..."
  }
}
```

### simulator_intro.md

Read this file fully. It defines the API contract, priority formulas, and
scheduling rules. The public `api_simulator.py` may expose additional commands
(like `batch_insert`) beyond the basic set — **inspect the source code** to
discover them.

---

## Step 2 — Compute Priority Scores

The `priority_method` in config determines the scoring formula. Let `u` =
urgency, `i` = importance, `t` = team_priority.

| Method       | Formula                                          |
|--------------|--------------------------------------------------|
| `urgency`    | `score = u`                                      |
| `eisenhower` | `score = u * i`                                  |
| `weighted`   | `0.6*u + 0.4*i` (no team_priority)               |
| `weighted`   | `0.5*u + 0.3*i + 0.2*t` (when team_priority present) |

### Tie-breaking (deterministic, apply in order)

1. **Earlier hard deadline** wins. A task *without* a deadline sorts **after**
   a task with one.
2. **Input order** in `tasks.json` (earlier index wins).

Sort tasks descending by score, then apply tie-breaks.

---

## Step 3 — Build the Initial Schedule

Use a greedy algorithm. Maintain a clock starting at `config.work_start`.

```
remaining = sorted task list (by priority)
schedule = []
missed = []
completed_ids = set()

while remaining is not empty:
    pick the highest-priority task T from remaining such that
        all of T's depends_on tasks are in completed_ids
        (if no such task exists, mark all remaining as missed and stop)

    start_time = max(current_clock, earliest possible after dependencies)
    end_time = start_time + T.duration_min

    if end_time > work_end:
        mark T as missed
        cascade: mark all tasks that transitively depend on T as missed
        remove T from remaining
        continue

    if T has a hard_deadline and end_time > hard_deadline:
        mark T as missed
        cascade misses for dependents
        remove T from remaining
        continue

    schedule T at [start_time, end_time) with status "scheduled"
    current_clock = end_time
    add T.id to completed_ids
    remove T from remaining
```

**Key rules:**
- Events are uninterrupted blocks.
- No partial credit for interrupted work (matters during emergencies).
- If a prerequisite is missed, **all transitively dependent tasks are missed**.
- Distinct task IDs remain distinct even when titles are equal.

---

## Step 4 — Submit to the Calendar API

### Protocol

The API is at `/app/api_simulator.py`. It reads JSON commands from stdin (one
per line) and writes JSON responses to stdout. State persists in
`/tmp/calendar_state.json` across invocations.

**The first mutating request MUST be `clear`.**

### Basic flow

```
1. {"cmd":"clear","calendar_id":"..."}
2. For each scheduled event (note: include "status" so it is stored in calendar state):
   {"cmd":"insert","calendar_id":"...","event":{"task_id":"...","title":"...","start":"...","end":"...","status":"scheduled"}}
3. {"cmd":"list","calendar_id":"..."}  # verify
```

> **⚠ Event payload must include `status`**: The simulator persists the
> entire event object. The test strips only `id` and compares the
> remaining fields against `output.json`. If `status` is missing from the
> insert payload, the calendar state will lack it and the comparison fails.

### Batch insertion (when available)

Inspect `api_simulator.py` source. If it handles `batch_insert`, use:

```json
{"cmd":"batch_insert","calendar_id":"...","events":[{"task_id":"...","title":"...","start":"...","end":"...","status":"scheduled"}, ...]}
```

Each event in the `events` array must include `status` just like individual inserts.

### Transient errors

If `api_simulator.py` has error injection (`error_rate > 0` or `rate_limit > 0`),
responses may return `{"status":"error",...}`. **Retry the same logical
operation** until it succeeds. Record every attempt (including errors) in
`history.jsonl`.

### Recording history

Every API request/response pair goes into `/app/history.jsonl`, one JSON object
per line:

```json
{"request":{...},"response":{...}}
```

Record **all** attempts, including failed ones.

---

## Step 5 — Emergency Replanning

Process emergencies in chronological `arrival_time` order. For each emergency:

### 5a. Preserve past events

Keep all calendar events whose `end` time is **at or before** the emergency's
`arrival_time`. These are untouchable.

### 5b. Delete future events

Delete **every** event whose `end` is **after** the `arrival_time`. This
includes an event currently in progress (its `start` ≤ arrival < its `end`).

For each deleted event, issue a `delete` API call and record it.

The interrupted normal task gets **no partial credit** — it returns to the
remaining-task pool at its **full original duration**.

### 5c. Insert the emergency

Insert the emergency event at exactly its `arrival_time`. The event payload
sent to the API must include `"status": "emergency"`. It must finish by:
- Its own `hard_deadline` (if present)
- `config.work_end`

If the emergency cannot fit, it still must be inserted (the spec requires it).
Record its status as `"emergency"`.

### 5d. Reschedule remaining normal tasks

Starting at the emergency's end time, rebuild the remaining normal plan using
the same priority and dependency rules from Step 3. These events get status
`"rescheduled"`.

### 5e. Repeat for later emergencies

If multiple emergencies exist, repeat 5a–5d for each subsequent one.

---

## Step 6 — Write Outputs

### /app/output.json

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
    "completed": ["A", "B", "D"],
    "missed": ["C", "E"],
    "total_tasks": 5,
    "completed_count": 3,
    "missed_count": 2
  }
}
```

**Status values:**
- `"scheduled"` — normal task placed in the initial plan
- `"rescheduled"` — normal task placed after an emergency replanning
- `"emergency"` — an emergency event

**Schedule must be chronological and non-overlapping.**

`completion_summary.completed` lists task IDs that have a calendar event
(scheduled or rescheduled). `missed` lists task IDs that do not. Emergencies
are not counted in completed/missed (they are always executed).

`total_tasks` = count of normal tasks in `tasks.json`.

### /app/history.jsonl

One JSON object per line, each with `request` and `response` keys. Must
include every API interaction in chronological order.

---

## Time Arithmetic Helper

All times are `HH:MM` strings in 24-hour format. Convert to minutes since
midnight for arithmetic:

```python
def to_minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"
```

---

## Interaction Pattern with api_simulator.py

Use a helper function to send commands and capture responses:

```python
import json, subprocess, os

HISTORY = []
CALENDAR_ID = "..."  # from tasks.json config

def api_call(cmd_dict):
    """Send one command, record in history, return response."""
    global HISTORY
    result = subprocess.run(
        ["python3", "/app/api_simulator.py"],
        input=json.dumps(cmd_dict) + "\n",
        capture_output=True, text=True
    )
    resp = json.loads(result.stdout.strip().split("\n")[-1])
    HISTORY.append({"request": cmd_dict, "response": resp})
    return resp

def api_call_with_retry(cmd_dict, max_retries=10):
    """Retry on transient errors."""
    for attempt in range(max_retries):
        resp = api_call(cmd_dict)
        if resp.get("status") == "ok":
            return resp
    raise RuntimeError(f"Failed after {max_retries} attempts: {cmd_dict}")
```

**Submitting events — always include `status` in the event payload:**

```python
def submit_event(calendar_id, event_dict):
    """Insert one event, including its status field."""
    # event_dict MUST contain: task_id, title, start, end, status
    api_call_with_retry({
        "cmd": "insert",
        "calendar_id": calendar_id,
        "event": event_dict  # pass the full dict, not a stripped copy
    })
```

**Important**: For batch operations during emergency replanning (multiple
deletes + inserts), send each command separately and record each one.

---

## Verification Checklist

Before declaring completion, verify:

1. **Calendar state matches output.json**: Run `{"cmd":"list",...}` and confirm
   the events match the schedule array exactly (after stripping `id` from
   each calendar event). All other fields — `task_id`, `title`, `start`,
   `end`, **`status`** — must be identical in both.
2. **No overlapping events**: All events are chronological, non-overlapping.
3. **Dependencies respected**: For every completed task with `depends_on`, all
   prerequisites appear earlier in the schedule.
4. **Deadlines respected**: No event ends after its task's `hard_deadline`.
5. **Work window respected**: All events are within `[work_start, work_end]`.
6. **Missed cascade correct**: If a task is missed, all transitive dependents
   are also missed.
7. **History complete**: Every API call (including retries and errors) is in
   `history.jsonl`.
8. **Emergency handling**: If emergencies exist, preserved events end at or
   before arrival, deleted events were removed, emergency is inserted at
   arrival time, remaining tasks are rescheduled after.
9. **First mutating call was `clear`**.
10. **output.json has correct structure** with both `schedule` and
    `completion_summary`.

---

## Common Pitfalls

- **Forgetting to clear first**: The spec requires the first mutating request
  to be `clear`. If you insert before clearing, the state will be wrong.
- **Not cascading misses**: When a task is missed, you must also miss all
  tasks that transitively depend on it.
- **Partial credit on interruption**: An interrupted task goes back to the pool
  at full duration, not remaining duration.
- **Tie-breaking errors**: Use deadline first (no deadline = last), then input
  order. Do not use alphabetical or ID-based tie-breaking.
- **Time format**: Always use `HH:MM` with leading zeros (e.g., `"09:00"`,
  not `"9:00"`).
- **History gaps**: Every single API call must be recorded, including retries
  and list/get verification calls.
- **Stale state across runs**: The simulator persists state in
  `/tmp/calendar_state.json`. Always `clear` before starting. If you need to
  restart, clear again.
- **Omitting `status` from insert events**: The API stores the event dict
  verbatim. The test compares calendar state (minus `id`) against
  `output.json`. If `status` is not in the insert payload, the calendar
  will lack it and the test fails. Always pass the full event object
  (including `status`) to the insert/batch_insert call.
- **Ignoring api_simulator.py source**: Some variants add `batch_insert` or
  other commands. Always inspect the file for capabilities beyond the basic
  set documented in simulator_intro.md.

---

## Dependency Resolution Algorithm

```python
def resolve_dependencies(tasks, missed_ids):
    """
    Given remaining tasks and already-missed IDs,
    return (schedulable_order, newly_missed_ids).
    """
    task_map = {t["id"]: t for t in tasks}
    missed = set(missed_ids)
    scheduled = set()
    order = []

    # Find tasks that can never be scheduled due to missed deps
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t["id"] in missed or t["id"] in scheduled:
                continue
            deps = t.get("depends_on", [])
            if any(d in missed for d in deps):
                missed.add(t["id"])
                changed = True

    return missed
```

Use this after marking any task as missed to cascade properly.

---

## Full Scheduling Pseudocode

```python
def schedule_tasks(tasks, config, start_clock):
    """
    Greedy scheduler. Returns (events, completed_ids, missed_ids).
    tasks: list of task dicts (should be pre-sorted by priority)
    config: {work_start, work_end, ...}
    start_clock: minutes since midnight for earliest slot
    """
    work_end = to_minutes(config["work_end"])
    clock = start_clock
    completed = set()
    missed = set()
    events = []

    # First cascade misses from dependencies
    missed = resolve_dependencies(tasks, missed)

    remaining = [t for t in tasks if t["id"] not in missed]

    max_iterations = len(remaining) * len(remaining) + 1  # safety
    iteration = 0
    while remaining and iteration < max_iterations:
        iteration += 1
        placed = False

        for i, t in enumerate(remaining):
            deps = t.get("depends_on", [])
            if not all(d in completed for d in deps):
                continue

            start = clock
            end = start + t["duration_min"]

            if end > work_end:
                missed.add(t["id"])
                remaining.pop(i)
                # cascade
                missed = resolve_dependencies(
                    remaining + [t], missed
                )
                remaining = [r for r in remaining if r["id"] not in missed]
                placed = True
                break

            deadline = t.get("hard_deadline")
            if deadline and end > to_minutes(deadline):
                missed.add(t["id"])
                remaining.pop(i)
                missed = resolve_dependencies(
                    remaining + [t], missed
                )
                remaining = [r for r in remaining if r["id"] not in missed]
                placed = True
                break

            events.append({
                "task_id": t["id"],
                "title": t["title"],
                "start": to_time(start),
                "end": to_time(end),
                "status": "scheduled"  # or "rescheduled" in emergency context
            })
            completed.add(t["id"])
            clock = end
            remaining.pop(i)
            placed = True
            break

        if not placed:
            # All remaining have unmet deps — mark all as missed
            for t in remaining:
                missed.add(t["id"])
            break

    return events, completed, missed
```

### Submitting events to the API

After building the event list, submit each event **including all fields**
(task_id, title, start, end, status) to the calendar:

```python
# After clearing the calendar:
for evt in events:
    api_call_with_retry({
        "cmd": "insert",
        "calendar_id": calendar_id,
        "event": evt  # send the FULL event dict — status included
    })
```

The simulator stores the event dict verbatim. The test strips only `id`
and compares the remaining fields against `output.json`, so every field
in `output.json` must be present in the calendar state.

This pseudocode should be adapted to the specific variant's needs. The core
logic handles priority ordering (pre-sort), dependency checking, deadline
enforcement, and work-window constraints.
