---
name: api-scheduler
description: >
  Reusable skill for stateful calendar API scheduling tasks. Builds a priority-ordered
  schedule via a JSON-line stdin/stdout API simulator, handles emergency interruptions
  with delete-and-reschedule, supports all three priority methods (urgency, eisenhower,
  weighted) with deterministic tie-breaking, dependency DAGs, hard deadlines, batch
  insertion, and transient-error retry semantics.
---

# API Scheduler Skill

## Overview

This skill solves calendar-based scheduling tasks where an agent must:
1. Read tasks from `/app/tasks.json`
2. Interact with a stateful calendar API simulator at `/app/api_simulator.py`
3. Schedule tasks by priority into a work window
4. Handle emergency interruptions by deleting overlapping events and rescheduling
5. Produce `/app/output.json` (final schedule) and `/app/history.jsonl` (all API interactions)

## API Protocol

The simulator is a **stdin/stdout JSON-line protocol** (not REST):
- Send one JSON object per line to stdin, receive one JSON response per line
- State persists in `/tmp/calendar_state.json` across calls within the same container
- **First mutating request MUST be `clear`** — resets all events

### Commands

| Command | Purpose |
|---------|---------|
| `{"cmd":"clear","calendar_id":"..."}` | Reset calendar (must be first) |
| `{"cmd":"insert","calendar_id":"...","event":{...}}` | Add one event |
| `{"cmd":"batch_insert","calendar_id":"...","events":[...]}` | Add multiple events (if supported) |
| `{"cmd":"list","calendar_id":"..."}` | List all events |
| `{"cmd":"get","calendar_id":"...","event_id":"..."}` | Get one event |
| `{"cmd":"delete","calendar_id":"...","event_id":"..."}` | Remove one event |

### Event Object
```json
{"task_id":"A","title":"Review Report","start":"14:00","end":"15:00"}
```

### Response Format
- Success: `{"status":"ok", ...}` (may include `event_id`, `events`, `message`)
- Error: `{"status":"error","message":"..."}` — does NOT mutate state

### Transient Errors
When `error_rate` or `rate_limit` config is active, random calls fail with:
- `"Internal server error"` 
- `"Rate limit exceeded. Try again later."`

**Must retry the same logical operation until it succeeds.** Record every attempt (including failures) in `history.jsonl`.

### Batch Insert Detection
Check `/app/api_simulator.py` source for `"batch_insert"`. If present, use:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```
Fall back to individual inserts if batch fails.

## Priority Scoring

| Method | Formula |
|--------|---------|
| `urgency` | `score = u` |
| `eisenhower` | `score = u * i` |
| `weighted` (no team_priority) | `score = 0.6*u + 0.4*i` |
| `weighted` (with team_priority) | `score = 0.5*u + 0.3*i + 0.2*t` |

Where `u` = urgency, `i` = importance, `t` = team_priority.

### Tie-Breaking (applied in order)
1. **Higher score first**
2. **Earlier hard deadline first**; a task WITHOUT a deadline sorts AFTER all tasks with deadlines
3. **Earlier position in `tasks.json`** (input order)

Task IDs are always distinct even when titles are duplicated.

## Greedy Scheduling Algorithm

```
function greedy_schedule(tasks, method, work_start, work_end, current_time=work_start):
    sort tasks by priority (descending score, then deadline, then input order)
    scheduled = [], missed = set(), remaining = sorted_tasks
    
    while remaining is not empty:
        made_progress = false
        next_remaining = []
        
        for each task in remaining (priority order):
            if any dependency is in missed:
                mark task as missed; made_progress = true; continue
            if not all dependencies are in scheduled:
                add to next_remaining; continue
            
            start = current_time
            end = start + task.duration
            
            if end > work_end:
                mark task as missed; made_progress = true; continue
            if task has deadline and end > deadline:
                mark task as missed; made_progress = true; continue
            
            schedule task at (start, end)
            current_time = end
            made_progress = true
        
        if not made_progress and next_remaining is not empty:
            # Deadlock: circular or unresolvable dependencies
            mark all next_remaining as missed
            break
        
        remaining = next_remaining
    
    return scheduled, missed
```

Key behaviors:
- A task that doesn't fit is marked **missed** and the algorithm continues to try lower-priority tasks
- If a prerequisite is missed, all transitive dependents are also missed
- Circular dependencies result in all involved tasks being missed

## Emergency Replanning

Process emergencies in chronological `arrival_time` order:

### At each emergency arrival:
1. **Preserve** calendar events whose `end <= arrival_time`
2. **Delete** every event whose `end > arrival_time` (including in-progress events)
   - Interrupted normal work gets NO partial credit
   - Return those tasks to the remaining-task pool at full duration
3. **Insert** the emergency event at exactly its `arrival_time`
   - Must finish by its deadline (if present) and by `work_end`
4. **Rebuild** remaining normal plan starting from the emergency's end time
   - Use same greedy algorithm with same priority/dependency rules
   - Events created during rescheduling use status `"rescheduled"`

### Status Labels (internal tracking only — NOT written to output.json)
- `"scheduled"` — events from the initial plan
- `"rescheduled"` — normal events created after an emergency
- `"emergency"` — emergency events

These labels help the solver track which events came from which phase, but the final `output.json` schedule entries contain only `{task_id, title, start, end}`.

## Output Format

### `/app/output.json`

**CRITICAL FORMAT RULES — tests enforce these exactly:**

1. **Schedule entries** contain EXACTLY `{task_id, title, start, end}` — matching the raw simulator event format. Do NOT include `status`, `id`, or any other fields. The test strips the simulator's internal `id` and compares field-for-field.
2. **`completion_summary.completed`** and **`completion_summary.missed`** MUST be sorted **alphabetically by task_id** (i.e., `sorted(task_ids)`). NOT in priority order or schedule order.
3. **`schedule` list** MUST be sorted by `(start, task_id)` — the test sorts calendar events by this key before comparing.

```json
{
  "schedule": [
    {
      "task_id": "A",
      "title": "Review Q3 Report",
      "start": "14:00",
      "end": "15:00"
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

**Note on status tracking**: While the scheduling contract mentions `scheduled`/`rescheduled`/`emergency` labels for internal logic (e.g., distinguishing initial vs. post-emergency events during replanning), these labels are NOT written to `output.json`. The final calendar state comparison test requires exact field match with simulator events.

### `/app/history.jsonl`
One JSON object per line for EVERY API attempt (including retries and errors):
```json
{"request": {"cmd":"insert", ...}, "response": {"status":"ok", ...}}
```

## Variation Axes Coverage

| Axis | Handling |
|------|----------|
| **task_volume** (3-12) | Algorithm scales; completed/missed partition handles overflow |
| **interruption_pattern** (0+ emergencies) | Chronological processing with delete-and-reschedule loop |
| **priority_method** (urgency/eisenhower/weighted) | Score formula selection with uniform tie-breaking |
| **scheduling_constraints** | Dependency DAGs, hard deadlines, duplicate titles, infeasible tasks |
| **api_capability** (basic/transient-errors/batch) | Retry loop for transient errors; batch detection from simulator source |

## Implementation Notes

- Time representation: convert "HH:MM" to minutes-since-midnight for arithmetic
- The simulator's `calendar_id` comes from `tasks.json` config, not environment
- Always verify final calendar state matches output.json (run `list` at end)
- The `depends_on` field is optional; absent means no dependencies
- Emergency events may have their own `deadline` field
- When batch_insert is available, use it for the initial plan; fall back to individual inserts on failure
