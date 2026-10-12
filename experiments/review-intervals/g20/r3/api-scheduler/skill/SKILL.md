---
name: api-scheduler
description: Build priority-based schedules using a stateful calendar API, handle emergencies with replanning, and manage API interactions including transient errors and batch operations.
---

# API Scheduler Skill

## Overview

This skill handles scheduling tasks into a calendar API with priority ordering, dependency constraints, emergency replanning, and various API capabilities. The core workflow: read tasks → compute priorities → build schedule → interact with API → handle emergencies → output results.

## Core Algorithm

### 1. Priority Calculation

Compute a score for each task based on the `priority_method` specified in `config`:

- **urgency**: `score = urgency`
- **eisenhower**: `score = urgency * importance`
- **weighted** (no team_priority): `score = 0.6*urgency + 0.4*importance`
- **weighted** (with team_priority): `score = 0.5*urgency + 0.3*importance + 0.2*team_priority`

**Tie-breaking** (applied in order):
1. Higher score first
2. Earlier hard deadline first (tasks without deadlines sort after those with deadlines)
3. Original order in `tasks.json` (input order)

### 2. Initial Schedule Construction

**Critical**: Use repeated candidate selection, NOT a single pass through pre-sorted tasks. Dependencies may require scheduling lower-priority tasks before higher-priority ones.

```
remaining = all tasks (list of task objects)
scheduled_set = set()     # task IDs successfully scheduled
missed_set = set()        # task IDs marked missed
schedule = []             # ordered list of scheduled events
current_time = work_start

while remaining is not empty:
    # Filter: a task is eligible only if ALL its depends_on are resolved
    candidates = [t for t in remaining
                  if all(d in scheduled_set or d in missed_set
                         for d in t.depends_on or [])]

    if candidates is empty:
        # All remaining tasks have unresolvable deps (e.g., circular)
        for t in remaining:
            missed_set.add(t.id)
        break

    # Pick highest-priority candidate using sort key:
    # (-score, deadline_key, input_order)
    task = min(candidates, key=sort_key)

    # Cascade: if any dependency is in missed_set, this task is missed
    if any(d in missed_set for d in task.depends_on or []):
        missed_set.add(task.id)
        remaining.remove(task)
        continue

    # Try to schedule at current_time
    task_end = current_time + task.duration
    if (hasattr(task, 'deadline') and task.deadline and task_end > time_to_minutes(task.deadline)) \
       or task_end > work_end:
        missed_set.add(task.id)
    else:
        event = {
            'task_id': task.id,
            'title': task.title,
            'start': minutes_to_time(current_time),
            'end': minutes_to_time(task_end),
            'status': 'scheduled'  # or 'rescheduled' after emergency
        }
        schedule.append(event)
        scheduled_set.add(task.id)
        current_time = task_end

    remaining.remove(task)

# After scheduling all tasks:
# completed = sorted(scheduled_set)  # MUST be sorted alphabetically
# missed = sorted(missed_set)        # MUST be sorted alphabetically
```

**Key invariant**: Never reserve time for future emergencies. Build the initial plan greedily using repeated selection.

### 3. Emergency Replanning

Process emergencies in chronological `arrival_time` order:

```
for each emergency (sorted by arrival_time):
    # Step 1: Preserve completed events
    preserved = [e for e in schedule if time_to_minutes(e.end) <= arrival_time]

    # Step 2: Delete overlapping/future events
    deleted = [e for e in schedule if time_to_minutes(e.end) > arrival_time]
    for each deleted event:
        API call: delete(event_id)
        scheduled_set.remove(event.task_id)

    # Step 3: Insert emergency at its arrival time
    emergency_end = arrival_time + emergency.duration
    # Emergency must finish by its deadline (if present) and work_end
    emergency_event = {
        'task_id': emergency.id,
        'title': emergency.title,
        'start': minutes_to_time(arrival_time),
        'end': minutes_to_time(emergency_end),
        'status': 'emergency'
    }
    API call: insert emergency at [arrival_time, emergency_end]
    schedule = preserved + [emergency_event]
    current_time = emergency_end

    # Step 4: Rebuild remaining normal tasks using repeated selection
    # Explicitly construct remaining from deleted events (self-contained)
    deleted_task_ids = {e.task_id for e in deleted}
    remaining = [t for t in all_tasks if t.id in deleted_task_ids]
    # (same algorithm as Section 2)
    while remaining is not empty:
        candidates = [t for t in remaining
                      if all(d in scheduled_set or d in missed_set
                             for d in t.depends_on or [])]

        if candidates is empty:
            for t in remaining:
                missed_set.add(t.id)
            break

        task = min(candidates, key=sort_key)

        if any(d in missed_set for d in task.depends_on or []):
            missed_set.add(task.id)
            remaining.remove(task)
            continue

        task_end = current_time + task.duration
        if (hasattr(task, 'deadline') and task.deadline and task_end > time_to_minutes(task.deadline)) \
           or task_end > work_end:
            missed_set.add(task.id)
        else:
            event = {
                'task_id': task.id,
                'title': task.title,
                'start': minutes_to_time(current_time),
                'end': minutes_to_time(task_end),
                'status': 'rescheduled'  # Tasks after emergency use 'rescheduled'
            }
            schedule.append(event)
            scheduled_set.add(task.id)
            current_time = task_end

        remaining.remove(task)
```

**Critical rule**: Interrupted normal work receives no partial credit and returns to the pool at full duration.

### 4. Dependency Handling

Tasks may have `depends_on` fields listing prerequisite task IDs.

**Critical**: Dependencies are resolved through the repeated selection loop in Section 2 and Section 3 Step 4. Do NOT use a single-pass approach.

**Dependency resolution rules**:
1. A task is eligible for scheduling only if ALL its dependencies are in `scheduled_set` or `missed_set`
2. If ANY dependency is in `missed_set`, the task itself must be marked missed (cascade)
3. If all dependencies are in `scheduled_set`, the task can be scheduled (subject to deadline/window constraints)

**Cascade rule**: If a prerequisite is missed, all tasks that depend on it are also missed. This cascade happens naturally in the repeated selection loop.

**Example**:
- Task X: urgency=5, depends_on=["Y"], duration=30
- Task Y: urgency=1, no dependencies, duration=30

Even though X has higher priority, Y must be scheduled first because X depends on it. The repeated selection loop handles this correctly:
- Iteration 1: Only Y is eligible (X's dependency not resolved). Schedule Y.
- Iteration 2: X is now eligible. Schedule X.

## API Interaction Protocol

### Basic Commands

```json
{"cmd": "clear", "calendar_id": "..."}
{"cmd": "insert", "calendar_id": "...", "event": {"task_id": "...", "title": "...", "start": "HH:MM", "end": "HH:MM"}}
{"cmd": "list", "calendar_id": "..."}
{"cmd": "get", "calendar_id": "...", "event_id": "..."}
{"cmd": "delete", "calendar_id": "...", "event_id": "..."}
```

### Mandatory Sequence

1. **First operation must be `clear`** - always clear the calendar before building the schedule
2. Insert events in chronological order
3. Record every request/response in `history.jsonl`

### Handling Transient Errors

When `api_capability` includes `transient-errors`:

```python
def call_api_with_retry(command, max_retries=5):
    for attempt in range(max_retries):
        response = call_api(command)
        if response['status'] == 'ok':
            return response
        # Check for transient errors (retryable)
        msg = response.get('message', '').lower()
        if any(kw in msg for kw in ['rate limit', 'internal server', 'try again', 'transient']):
            continue  # transient - retry
        # Permanent error - don't retry
        break
    return response  # Return last response (success or permanent error)
```

**Record every attempt** in history.jsonl, including failed ones.

### Batch Insertion

When `api_capability` includes `batch`:

```json
{"cmd": "batch_insert", "calendar_id": "...", "events": [...]}
```

Use `batch_insert` for the initial plan to reduce API calls. Inspect `api_simulator.py` to confirm the command exists.

## Time Handling

```python
def time_to_minutes(time_str):
    """Convert 'HH:MM' to minutes since midnight"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def minutes_to_time(minutes):
    """Convert minutes since midnight to 'HH:MM'"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"
```

## Output Format

### output.json

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

**Critical output format requirements**:
1. **Schedule events MUST have `status` field** with values: `scheduled`, `rescheduled`, or `emergency`
   - `scheduled`: Normal task in initial plan
   - `rescheduled`: Normal task scheduled after an emergency
   - `emergency`: Emergency task itself
2. **`completed` and `missed` lists must be SORTED alphabetically** - not in schedule order. Tests expect `sorted(task_ids)`.
3. **Schedule events must be in chronological order** - sorted by `(start, task_id)`.
4. **Calendar API events do NOT have `status` field** - only `{task_id, title, start, end}`. The output includes status for tracking purposes, but when inserting into the calendar API, omit the status field.

### history.jsonl

One JSON object per line:

```json
{"request": {...}, "response": {...}}
```

Record every API call, including retries and errors.

**Critical**: Must include at least one successful `list` call. Tests verify this.

## Edge Cases

### Infeasible Tasks

A task is infeasible if:
- Duration exceeds available time window
- Cannot finish by deadline even if scheduled immediately
- Depends on a missed task

Mark infeasible tasks as `missed` and continue.

### Duplicate Titles

Tasks may have identical `title` values. Use `task_id` as the unique identifier.

### Work Windows

Tasks must fit within `[work_start, work_end]`. If a task would extend beyond `work_end`, mark it missed.

### Emergency During Work

When an emergency arrives at time T:
- Events with `end <= T` are preserved
- Events with `end > T` are deleted (even if already in progress)
- The interrupted task returns to the pool at full duration

## Implementation Checklist

1. Read `tasks.json` and `simulator_intro.md`
2. Calculate priority scores for all tasks
3. Build initial schedule using repeated selection (NOT single-pass)
4. Clear the calendar via API (mandatory first operation)
5. Insert all scheduled events via API (use batch if available)
   - **Calendar API events**: `{task_id, title, start, end}` only (NO `status` field)
6. **Make a `list` API call** to verify calendar state (required by tests)
7. Process emergencies chronologically:
   - Delete overlapping events
   - Insert emergency with `status: "emergency"`
   - Rebuild remaining schedule using repeated selection with `status: "rescheduled"`
8. Write `output.json`:
   - Schedule events: `{task_id, title, start, end, status}` (MUST have `status` field)
   - Status values: `scheduled`, `rescheduled`, or `emergency`
   - `completed` and `missed`: **SORTED alphabetically**
9. Write `history.jsonl` with all API interactions (must include successful `list`)
10. Verify final calendar state matches output.json schedule (after stripping `status` from output)

## Testing Strategy

After implementation:
- Verify all events are non-overlapping and chronological
- Verify all dependencies are satisfied (each task's depends_on are scheduled before it)
- Verify all deadlines are met (or tasks are marked missed)
- Verify calendar state matches output.json
- Verify history.jsonl contains all API calls
