---
name: api-scheduler
description: Build priority-based schedules using a stateful calendar API, handle emergencies through replanning, and manage API interactions including retries and batch operations.
---

# API Scheduler Skill

This skill addresses the task family defined by the calendar API scheduling contract. The family spans variations in task volume, interruption patterns, priority methods, scheduling constraints, and API capabilities.

A reference implementation is provided in `scripts/solve.py`.

## Core Algorithm

### 1. Priority Scoring

Compute task scores based on the `priority_method` from `config`:

- **urgency**: `score = urgency`
- **eisenhower**: `score = urgency * importance`
- **weighted** (without team_priority): `score = 0.6*urgency + 0.4*importance`
- **weighted** (with team_priority): `score = 0.5*urgency + 0.3*importance + 0.2*team_priority`

### 2. Priority Ordering

Sort tasks by:
1. **Score** (descending - higher is first)
2. **Hard deadline** (ascending - earlier deadline first; tasks without deadlines sort after those with deadlines)
3. **Original order** in tasks.json (ascending - preserves input order for ties)

### 3. Initial Schedule Construction

Greedy algorithm respecting dependencies:

```
cursor = work_start
completed = {}
remaining = tasks sorted by priority

while remaining:
    find highest-priority task whose depends_on are all in completed
    if no such task:
        mark all remaining as missed (dependency deadlock)
        break
    
    end_time = cursor + task.duration
    deadline_ok = (no deadline) or (end_time <= deadline)
    fits_in_day = end_time <= work_end
    
    if deadline_ok and fits_in_day:
        schedule task at [cursor, end_time]
        completed.add(task.id)
        cursor = end_time
        remaining.remove(task)
    else:
        mark task as missed
        remaining.remove(task)
        cascade: mark all tasks depending on this task as missed
```

### 4. Emergency Replanning

Process emergencies in chronological order by `arrival_time`:

```
for each emergency (sorted by arrival_time):
    arrival = emergency.arrival_time
    
    # Preserve completed work
    preserved = events where event.end <= arrival
    to_delete = events where event.end > arrival
    
    # Delete interrupted/future events
    for event in to_delete:
        api.delete(event.id)
    
    # Insert emergency at arrival time
    emerg_end = arrival + emergency.duration
    api.insert(emergency at [arrival, emerg_end])
    
    # Rebuild remaining normal tasks
    completed_ids = {event.task_id for event in preserved}
    remaining = tasks not in completed_ids and not previously missed
    
    rebuilt_schedule = build_schedule(remaining, emerg_end, work_end)
    
    for event in rebuilt_schedule:
        event.status = "rescheduled"
        api.insert(event)
    
    # Update missed list with newly missed tasks
    missed.extend(newly_missed)
```

### 5. API Interaction Protocol

**Required sequence:**
1. **First mutation must be `clear`** - resets calendar state
2. **Insert events** - one per task in schedule
3. **Verify with `list`** - confirm state matches plan
4. **Handle emergencies** - delete, insert, rebuild as needed

**Event-ID tracking (critical for emergency replanning):**

The simulator assigns auto-generated event IDs (evt_0, evt_1, ...) on insert. You must capture and store the mapping `task_id → event_id` at insert time:

```python
event_map = {}  # task_id → event_id
for task in scheduled_tasks:
    resp = api_insert(task)
    event_map[task["id"]] = resp["event_id"]
```

When an emergency arrives:
- Query `list` to find all events with `end > arrival_time`
- Delete each by its `event_id` from your map
- Insert the emergency event
- Rebuild normal tasks from `emerg_end`, inserting with status `"rescheduled"`
- Update the map with new event_ids for rescheduled tasks

Without this mapping, you cannot delete the correct events during replanning. The simulator's `next_id` counter keeps incrementing across deletions, so you cannot predict IDs — you must record them.

**Error handling and retry logic:**

For the `transient-errors` API capability, wrap every API call in a retry loop:

```python
def api_call(cmd):
    while True:
        resp = send_to_simulator(cmd)
        history.append({"request": cmd, "response": resp})
        if resp["status"] == "ok":
            return resp
        msg = resp.get("message", "")
        if "Rate limit" in msg or "Internal server" in msg:
            continue  # transient — retry
        else:
            return resp  # permanent error — don't retry
```

**Key:** Every attempt (including errors) goes into history.jsonl. A single logical operation might produce 3 history entries (2 errors + 1 success).

**Batch operations:**

If `api_simulator.py` exposes `batch_insert`, use it for the initial plan:

```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

### 6. Output Format

**output.json:**
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

**Critical formatting rules:**
- Schedule entries MUST contain exactly: `task_id`, `title`, `start`, `end`, `status`
- The `status` field is required: `"scheduled"` for initial plan, `"rescheduled"` after emergency, `"emergency"` for emergency events
- The `completed` and `missed` lists must be **sorted alphabetically**
- The test `test_titles_statuses_and_durations_are_exact` asserts `set(item) == {"task_id", "title", "start", "end", "status"}`
- The test `test_final_calendar_state_matches_output` uses `strip_remote_id` which strips both `id` and `status` from simulator events before comparison

**history.jsonl:**
```json
{"request": {...}, "response": {...}}
```
One JSON object per line, recording every API interaction (including errors).

## Variation Handling

### Task Volume (3-12 tasks)
- Algorithm scales linearly
- Watch for cases where total duration exceeds available time
- Dependency chains may create infeasible schedules

### Interruption Patterns
- **No interruption**: straightforward initial schedule
- **One emergency**: single replanning cycle
- **Multiple emergencies**: process chronologically, each invalidates overlapping/future events

### Priority Methods
- Implement all three scoring formulas
- Tie-breaking is deterministic: deadline → input order

### Scheduling Constraints
- **Work windows**: respect `work_start` and `work_end`
- **Hard deadlines**: tasks must finish by deadline or be marked missed
- **Dependencies**: `depends_on` creates ordering constraints; missed prerequisites cascade
- **Duplicate titles**: use `task_id` for identity, not title
- **API errors**: handle gracefully with retries

### API Capabilities
- **basic**: individual insert/delete/list/clear/get
- **transient-errors**: implement retry logic for rate limits and server errors
- **batch**: use `batch_insert` when available for efficiency

## Implementation Checklist

1. ✓ Read tasks.json and extract config
2. ✓ Compute priority scores and sort tasks
3. ✓ Build initial schedule with dependency checking
4. ✓ Clear calendar (first mutation)
5. ✓ Insert all scheduled events, capturing event_id mappings
6. ✓ Verify with list command
7. ✓ Process emergencies chronologically (if any)
8. ✓ For each emergency: delete overlapping events, insert emergency, rebuild remaining
9. ✓ Write output.json with schedule and completion_summary
10. ✓ Write history.jsonl with all API interactions

## Common Pitfalls

- **Forgetting to clear first**: The first successful mutation must be `clear`
- **Not tracking event_ids**: Without the task_id → event_id map, you cannot delete the correct events during emergency replanning
- **Ignoring dependencies**: Tasks with unmet dependencies cannot be scheduled
- **Missing deadline checks**: Both work_end and hard deadline must be satisfied
- **Partial credit for interrupted work**: Interrupted tasks return to pool at full duration
- **Not recording errors**: Every API attempt (including failures) goes in history.jsonl
- **Confusing task_id with event_id**: Events have auto-generated IDs (evt_0, evt_1, ...); tasks have user-defined IDs
- **Missing status field in output**: Schedule entries MUST include `status` field ("scheduled", "rescheduled", or "emergency")
- **Unsorted completed/missed lists**: Both lists must be sorted alphabetically, not in schedule order
- **Emergency identifier field**: Emergencies may use `id` or `task_id` as the identifier field; handle both

## Reference Implementation

The script `scripts/solve.py` implements the complete algorithm with:
- All three priority methods
- Dependency-aware scheduling with cascade on missed prerequisites
- Emergency replanning with proper event-ID tracking
- Retry logic for transient API errors
- Complete history recording
- Support for both `id` and `task_id` fields in emergency definitions

To use: place the script in `/app/solve.py` and run with `python3 /app/solve.py`. It reads `/app/tasks.json` and writes `/app/output.json` and `/app/history.jsonl`.
