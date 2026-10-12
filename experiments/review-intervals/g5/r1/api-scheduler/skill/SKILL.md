---
name: api-scheduler
description: Build priority-based schedules using a stateful calendar API, handle emergencies with stateful replanning, and manage transient API errors. Supports urgency/eisenhower/weighted priority methods, dependency DAGs, hard deadlines, and batch insertion when available.
---

# API Scheduler Skill

This skill guides an agent through building a priority-based schedule using a stateful calendar API simulator. The task family varies across five dimensions: task volume (3-12 tasks), interruption patterns (none to multiple emergencies), priority methods (urgency/eisenhower/weighted), scheduling constraints (dependencies, deadlines, work windows), and API capabilities (basic/transient-errors/batch).

## Core Workflow

1. **Read inputs**: Load `/app/tasks.json` containing tasks, emergencies, and config
2. **Read API docs**: Parse `/app/simulator_intro.md` for the scheduling contract
3. **Inspect simulator**: Check `/app/api_simulator.py` for available commands (especially `batch_insert`)
4. **Clear calendar**: First API call must be `clear`
5. **Compute priorities**: Score tasks using the specified method
6. **Build initial plan**: Greedy scheduling respecting dependencies and deadlines
7. **Submit to API**: Insert events (use `batch_insert` if available, otherwise individual inserts)
8. **Handle emergencies**: Process chronologically with delete-and-rebuild protocol
9. **Verify state**: Call `list` to verify the final calendar state
10. **Write outputs**: Generate `/app/output.json` and `/app/history.jsonl`

## Priority Scoring

The `priority_method` in config determines how tasks are ranked:

- **urgency**: `score = urgency`
- **eisenhower**: `score = urgency * importance`
- **weighted** (no team_priority): `score = 0.6*urgency + 0.4*importance`
- **weighted** (with team_priority): `score = 0.5*urgency + 0.3*importance + 0.2*team_priority`

**Tie-breaking** (applied in order):
1. Higher score first
2. Earlier hard deadline first; tasks without deadline sort after those with one
3. Original order in `tasks.json`

## Initial Plan Construction

Build the schedule greedily starting from `config.work_start`:

```
cursor = work_start
remaining = all task IDs
scheduled = empty set

while remaining is not empty:
    schedulable = tasks in remaining whose dependencies are all in scheduled
    
    if schedulable is empty:
        mark all remaining as missed (dependency deadlock)
        break
    
    sort schedulable by priority (highest first)
    chosen = schedulable[0]
    
    start = cursor
    end = start + chosen.duration
    
    if end > work_end:
        mark chosen as missed
        remove chosen from remaining
        BFS-cascade: mark all transitive dependents as missed (see below)
        continue
    
    if chosen has deadline and end > deadline:
        mark chosen as missed
        remove chosen from remaining
        BFS-cascade: mark all transitive dependents as missed (see below)
        continue
    
    schedule chosen at [start, end]
    add chosen to scheduled
    remove chosen from remaining
    cursor = end
```

**Dependency cascade (BFS)**: When a task is marked missed, all tasks that depend on it — transitively, including fan-out patterns — must also be marked missed. Use a BFS that tracks *all* newly-missed tasks per iteration, not just the last one:

```
def cascade_missed(root_id, remaining, missed_list):
    newly_missed = [root_id]
    while newly_missed is not empty:
        next_batch = empty list
        for each mid in newly_missed:
            for each tid in remaining:
                if mid is in tid.depends_on:
                    remove tid from remaining
                    add tid to missed_list
                    add tid to next_batch
        newly_missed = next_batch
```

A common bug is to overwrite a single `missed_id` variable with each removed task, which only cascades from the *last* sibling and misses dependents of earlier siblings in fan-out patterns (e.g., A→B, A→C, B→D, C→E — if A is missed, D depends on B which depends on A, but a single-variable cascade from C would never reach D).

## API Interaction

### Command Format

Every request must include `calendar_id` from config. Basic commands:

```json
{"cmd": "clear", "calendar_id": "..."}
{"cmd": "insert", "calendar_id": "...", "event": {"task_id": "...", "title": "...", "start": "HH:MM", "end": "HH:MM"}}
{"cmd": "list", "calendar_id": "..."}
{"cmd": "get", "calendar_id": "...", "event_id": "..."}
{"cmd": "delete", "calendar_id": "...", "event_id": "..."}
```

**Important**: The `event` object sent to the API must contain only `task_id`, `title`, `start`, and `end`. The `status` field is tracked internally and included in output.json, but is not sent to the API simulator.

### Transient Error Handling

The simulator may inject transient errors (`error_rate`, `rate_limit`). **Every API call must be wrapped in a retry loop**:

```python
def api_call(cmd, max_retries=5):
    for attempt in range(max_retries):
        response = send_to_simulator(cmd)
        log_to_history({"request": cmd, "response": response})
        
        if response["status"] == "ok":
            return response
        
        # Retry on transient errors
        msg = response.get("message", "")
        if "Rate limit" in msg or "Internal server error" in msg or "Try again" in msg:
            continue
        
        # Non-retryable error
        return response
    
    return last_response  # all retries exhausted
```

**Critical**: Log EVERY attempt to `history.jsonl`, including failures. The contract requires a complete audit trail.

### Batch Insert Detection

Before submitting the initial plan, inspect `/app/api_simulator.py` for a `batch_insert` command:

```bash
grep -n "batch_insert" /app/api_simulator.py
```

If found, submit the entire initial plan as one batch:

```json
{"cmd": "batch_insert", "calendar_id": "...", "events": [...]}
```

Otherwise, submit individual `insert` calls. Track returned `event_id` values for later deletion during emergency replanning.

## Emergency Replanning Protocol

Process emergencies in chronological order by `arrival_time`. For each emergency:

### Step 1: Preserve Completed Events

Keep all events whose `end <= arrival_time`. These represent work that finished before the emergency arrived.

### Step 2: Delete Interrupted/Future Events

Delete every event whose `end > arrival_time`. This includes:
- Events currently in progress (started before arrival but ending after)
- Events scheduled for later

**Critical**: Interrupted tasks receive **no partial credit**. They return to the remaining-task pool at their **full original duration**.

```python
for evt in current_events:
    if time_to_min(evt["end"]) > arrival_min:
        delete_event(evt["event_id"])
        if evt["status"] in ("scheduled", "rescheduled"):
            # Return to remaining pool
            remaining_tasks.add(evt["task_id"])
```

### Step 3: Insert Emergency Event

Insert the emergency at exactly its `arrival_time`:

```json
{
  "task_id": "EM1",
  "title": "...",
  "start": "arrival_time",
  "end": "arrival_time + duration"
}
```

The emergency must finish by its own deadline (if present) and by `work_end`.

**Important**: The `status` field is tracked **internally only** — never send it to the API and never include it in `output.json` schedule events. The remote simulator state doesn't track status, and tests compare output directly with remote state. Internally, you need status to distinguish which events to delete during emergencies (only delete events with status "scheduled" or "rescheduled", not "emergency").

### Step 4: Rebuild Remaining Plan

Starting from the emergency's `end` time, rebuild the remaining normal-task plan using the same priority/dependency rules as the initial plan. Use status `"rescheduled"` for these events.

**Critical**: Pass the preserved task IDs as `pre_completed` so dependency checking works correctly. Tasks that completed before the emergency (preserved events) should be considered when evaluating dependencies for remaining tasks.

```python
cursor = emergency_end
completed_before = set(e["task_id"] for e in preserved)
remaining = tasks not in completed_before
rebuild_schedule(remaining, cursor, status_label="rescheduled", pre_completed=completed_before)
```

Without `pre_completed`, a task depending on a preserved task would incorrectly see its dependency as unsatisfied.

### Multiple Emergencies

Repeat the entire 4-step protocol for each emergency in chronological order. Each emergency triggers a fresh delete-and-rebuild cycle.

## Status Labels

Include the `status` field in output.json schedule events with these values:

- `"scheduled"`: Events in the initial plan (before any emergencies)
- `"rescheduled"`: Normal events created after an emergency
- `"emergency"`: Emergency events themselves

**Important**: The `status` field is used both internally (for emergency replanning logic) and externally (in output.json). Track status for each event throughout the scheduling process and include it in the final output.

## Output Format

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
    "completed": ["A", "B"],
    "missed": ["C"],
    "total_tasks": 3,
    "completed_count": 2,
    "missed_count": 1
  }
}
```

**Critical requirements**:
- The schedule must be sorted chronologically
- **Schedule events MUST include the `status` field** with values: "scheduled", "rescheduled", or "emergency"
- **`completed` and `missed` lists must be sorted alphabetically** (not in schedule order)
- The completion_summary tracks which normal tasks were completed vs missed
- Emergency task IDs are NOT included in completed/missed counts (only normal tasks)

## History Logging

Write `/app/history.jsonl` with one JSON object per line:

```json
{"request": {...}, "response": {...}}
```

Log **every** API attempt, including retries and failures. This is a mandatory audit trail.

## Time Utilities

```python
def time_to_min(t):
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m):
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{m // 60:02d}:{m % 60:02d}"
```

## Common Pitfalls

1. **Forgetting to clear first**: The first API call must be `clear`
2. **Not logging retries**: Every API attempt (success or failure) must be in history.jsonl
3. **Partial credit for interrupted tasks**: Interrupted tasks return at full duration
4. **Missing dependency cascade**: When a task is missed, all its dependents are also missed
5. **Wrong status labels**: Use "scheduled", "rescheduled", "emergency" correctly
6. **Not checking for batch_insert**: Inspect the simulator before deciding how to submit
7. **Emergency deadline violations**: Emergencies must finish by their own deadline and work_end
8. **Incorrect tie-breaking**: Score → deadline (earlier first, no deadline last) → original order
9. **Missing `status` in output**: Schedule events in output.json MUST include the `status` field
10. **Unsorted `completed`/`missed` lists**: Both `completed` and `missed` in completion_summary must be sorted alphabetically, not in schedule order
11. **Missing `list` API call**: After inserting events, call the `list` command to verify the calendar state. Tests expect at least one successful `list` call in history.jsonl

## Verification Checklist

Before finalizing:

- [ ] Calendar was cleared first
- [ ] All API attempts logged in history.jsonl
- [ ] At least one successful `list` API call in history.jsonl
- [ ] Schedule is chronological and non-overlapping
- [ ] Status labels are correct (scheduled/rescheduled/emergency) and included in output
- [ ] Dependencies are respected (no task scheduled before its prerequisites)
- [ ] Deadlines are met (or tasks correctly marked missed)
- [ ] Emergencies processed in chronological order
- [ ] Interrupted tasks returned to pool at full duration
- [ ] output.json schedule events INCLUDE `status` field
- [ ] completion_summary `completed` and `missed` lists are sorted alphabetically
- [ ] output.json matches final simulator state exactly
