---
name: api-scheduler
description: Build priority-based schedules using a stateful calendar API, handle emergencies with replanning, and manage API variations (batch insertion, transient errors).
---

# API Scheduler Skill

This skill solves the **api-scheduler family**: tasks that require building a priority-ordered schedule, submitting it to a stateful calendar API, and revising the schedule when emergencies arrive.

## Family Definition

The family is defined by two sources:
- **spec.yaml**: Declares variation axes (task volume, interruption patterns, priority methods, scheduling constraints, API capabilities)
- **simulator_intro.md**: Defines the scheduling contract (priority scoring, dependency handling, emergency replanning rules)
- **tasks.json**: Provides the concrete instance (tasks, emergencies, config)
- **api_simulator.py**: Implements the calendar API (may vary in capabilities)

## Core Algorithm

### 1. Priority Scoring

Compute a score for each task based on `config.priority_method`:

```python
def compute_score(task, method):
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", 0)
    
    if method == "urgency":
        return u
    elif method == "eisenhower":
        return u * i
    elif method == "weighted":
        if "team_priority" in task:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
```

**Sort order**: Higher score first → earlier deadline (tasks without deadline sort after) → original input order.

### 2. Initial Schedule Construction

Build the schedule greedily starting at `config.work_start`:

```
while tasks remain:
    sort remaining tasks by priority
    for each task (highest priority first):
        if dependencies not met:
            if any dependency is missed:
                mark this task as missed
            else:
                skip (try next task)
        else:
            if task fits in window and meets deadline:
                schedule it at current_time
                advance current_time
            else:
                mark as missed
```

**Key rules**:
- Tasks are uninterrupted and non-overlapping
- A task is scheduled only if it completes by both its deadline (if present) and `work_end`
- If a task can't fit, mark it missed and continue with lower-priority tasks
- If a dependency is missed, all dependent tasks are also missed

### 3. API Interaction Protocol

#### Detection Phase

Before interacting with the API, inspect `api_simulator.py` to detect capabilities:

```python
with open("/app/api_simulator.py") as f:
    content = f.read()
    supports_batch = "batch_insert" in content
```

#### Submission Phase

**If batch_insert is supported**:
```
clear → batch_insert(all initial events)
```

**Otherwise**:
```
clear → insert(event1) → insert(event2) → ...
```

**Critical**: The first successful mutating request MUST be `clear`.

#### History Tracking

Record EVERY request and response in `history.jsonl`:
```json
{"request": {...}, "response": {...}}
```

This includes failed attempts, list/get calls, and delete operations.

### 4. Transient Error Handling

The API may inject transient errors (rate limits, internal errors). The retry strategy:

```python
def send(cmd, max_retries=15):
    for attempt in range(max_retries):
        response = send_to_api(cmd)
        record_in_history(cmd, response)
        if response["status"] == "ok":
            return response
        # Any non-ok is retryable
    raise RuntimeError("Failed after max retries")
```

**Key**: Retry on ANY error response, not just specific error messages. Well-formed requests should eventually succeed.

### 5. Simulator is a Pass-Through Store

The simulator stores and returns exactly the fields you send in the `event` dict. This means:

- If you want `status` in the remote state (which tests compare against output), you MUST include `status` in every `api.insert()` call
- The test `test_final_calendar_state_matches_output` strips only the internal `id` field, then compares `remote == output["schedule"]` with exact equality
- Both sides must have identical keys: `{task_id, title, start, end, status}`

**Critical**: Include `status` in ALL insert calls:
- Initial plan inserts (both individual and batch paths)
- Emergency inserts
- Rescheduled task inserts

### 6. Emergency Replanning

Process emergencies in chronological order by `arrival_time`. For each emergency:

#### Step 1: Preserve Completed Work
Keep events whose `end <= arrival_time`.

#### Step 2: Delete Interrupted Events
```
list() → get all current events
for each event where end > arrival_time:
    delete(event_id)
```

Both `list` and `delete` calls must be recorded in history.

#### Step 3: Return Interrupted Tasks to Pool
Tasks from deleted events (except other emergencies) return to the remaining-task pool at full duration.

#### Step 4: Insert Emergency
```
insert({
    "task_id": emergency.id,
    "title": emergency.title,
    "start": arrival_time,
    "end": arrival_time + duration,
    "status": "emergency"
})
```

The emergency must finish by its deadline (if present) and by `work_end`.

#### Step 5: Rebuild Remaining Plan
Starting from the emergency's end time, rebuild the normal-task schedule using the same priority and dependency rules. Mark these events as `"rescheduled"`.

#### Step 6: Update State
```
all_events = preserved + [emergency] + new_rescheduled_events
all_missed = new_missed_from_rebuild
```

Repeat for each subsequent emergency. Events from a previous emergency's rescheduling may themselves be deleted by a later emergency.

### 7. Output Format

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

**CRITICAL REQUIREMENTS**:

1. **Schedule events MUST have exactly 5 fields**: `task_id`, `title`, `start`, `end`, `status`. The `status` field is REQUIRED by the spec and tests. Status values:
   - `"scheduled"`: Normal task in initial plan
   - `"rescheduled"`: Normal task placed after an emergency
   - `"emergency"`: Emergency task

2. **completed and missed must be SORTED alphabetically**: Both lists must be sorted by task_id, not in schedule order.

3. **Schedule must be sorted chronologically**: Sort by `(start_time, task_id)`.

4. **Completion summary counts ONLY normal tasks**: Emergency tasks appear in the schedule but are NOT included in `completed`, `missed`, or the counts. This ensures:

```
total_tasks = completed_count + missed_count
```

Always holds. Emergency tasks are tracked in the schedule for API state consistency but excluded from completion metrics.

## Variation Axes

### task_volume (3-12 tasks)
- Small volumes: All tasks may fit
- Large volumes: Some tasks will be missed; dependency cascading becomes important

### interruption_pattern (freeform)
- No emergencies: Straightforward initial schedule
- One emergency: Single replanning pass
- Multiple emergencies: Sequential replanning; later emergencies may delete events from earlier replanning

### priority_method (enum: urgency, eisenhower, weighted)
- Determines scoring formula (see Section 1)
- Tie-breaking is always: earlier deadline → original input order

### scheduling_constraints (freeform)
- **Dependencies**: `depends_on` array; cascading misses
- **Deadlines**: Hard constraints; tasks that miss deadlines are marked missed
- **Work windows**: `work_start` and `work_end` define the scheduling horizon
- **Duplicate titles**: Task IDs remain distinct even when titles are equal
- **Infeasible requirements**: Tasks that can't fit are marked missed

### api_capability (enum: basic, transient-errors, batch)
- **basic**: Individual insert calls
- **transient-errors**: Retry loop required; record all attempts in history
- **batch**: Detect `batch_insert` in simulator source; submit initial plan atomically

## Implementation Checklist

- [ ] Read `tasks.json` and `simulator_intro.md`
- [ ] Inspect `api_simulator.py` for `batch_insert` support
- [ ] Compute priority scores per `config.priority_method`
- [ ] Build initial schedule respecting dependencies, deadlines, work window
- [ ] Start API simulator subprocess
- [ ] Send `clear` command (must be first mutating request)
- [ ] Submit initial plan (batch or individual inserts)
- [ ] Record all API interactions in `history.jsonl`
- [ ] Process emergencies chronologically:
  - [ ] List current events
  - [ ] Delete events with `end > arrival_time`
  - [ ] Insert emergency at `arrival_time`
  - [ ] Rebuild remaining plan from emergency end
  - [ ] Insert rescheduled events
- [ ] Write `output.json` with schedule and completion summary
- [ ] Verify final simulator state matches `output.json`

## Common Pitfalls

1. **Not clearing first**: The first successful mutating request must be `clear`
2. **Keyword-based retry filtering**: Retry on ANY error, not just specific messages
3. **Missing list() in emergency handling**: The list call is part of the protocol and must be recorded
4. **Forgetting to return interrupted tasks**: Deleted normal events return to the pool at full duration
5. **Missing status field in output**: Each schedule event MUST have exactly 5 fields: `task_id`, `title`, `start`, `end`, `status`. The `status` field is required by the spec and tests. Use `"scheduled"` for initial plan, `"rescheduled"` for post-emergency, `"emergency"` for emergency tasks.
6. **Unsorted completed/missed lists**: Both `completed` and `missed` must be sorted alphabetically by task_id, not in schedule order
7. **Dependency cascading**: If task A is missed and B depends on A, B is also missed
8. **Batch detection from config**: Detect batch support by reading simulator source, not from tasks.json
9. **Emergency tasks in completion_summary**: Emergency tasks appear in the schedule but must NOT be counted in `completed`, `missed`, or the counts. Only normal tasks from `tasks.json` count.
10. **Unsorted schedule**: The schedule must be sorted by `(start_time, task_id)`, not just by start time
