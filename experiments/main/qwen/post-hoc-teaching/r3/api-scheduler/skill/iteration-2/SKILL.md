---
name: api-scheduler
description: >
  Solve stateful calendar API scheduling problems. Read tasks from tasks.json,
  compute priority-ordered schedules respecting dependencies/deadlines/work windows,
  interact with a JSON-line calendar API simulator (clear/insert/list/delete/batch_insert),
  handle chronological emergencies by deleting interrupted events and rebuilding,
  and produce output.json + history.jsonl. Covers urgency/eisenhower/weighted scoring,
  dependency DAGs, transient error retries, batch API detection, and multi-emergency replanning.
---

# API Scheduler Skill

## Overview

This skill solves a family of calendar-scheduling tasks where an agent must:
1. Read task definitions from `/app/tasks.json`
2. Read the API contract from `/app/simulator_intro.md`
3. Inspect `/app/api_simulator.py` for capabilities (batch, error injection)
4. Compute a priority-ordered schedule
5. Interact with the stateful calendar API simulator
6. Handle emergencies that invalidate parts of the schedule
7. Write `/app/output.json` and `/app/history.jsonl`

## Architecture

Use the provided `solve.py` reference script. It can be copied to `/app/solve.py` and executed directly. The script handles all variation dimensions from the spec.

## Core Algorithm

### 1. Priority Scoring

Compute a numeric score for each task based on `config.priority_method`:

| Method | Formula |
|--------|---------|
| `urgency` | `score = urgency` |
| `eisenhower` | `score = urgency * importance` |
| `weighted` (no team_priority) | `score = 0.6*urgency + 0.4*importance` |
| `weighted` (with team_priority) | `score = 0.5*urgency + 0.3*importance + 0.2*team_priority` |

### 2. Deterministic Sort Order

Sort tasks by:
1. **Higher score first** (descending)
2. **Earlier deadline first**; tasks without a deadline sort AFTER tasks with one
3. **Original order in tasks.json** (ascending index) as final tiebreaker

**Critical: Stable Index References.** Compute `original_indices` **once** from the full `tasks.json` list and pass it to every `build_schedule` call (initial + emergency rebuilds). Never recompute indices from a subset — the tiebreaker must always reference the original document order, not the order of a derived collection. This prevents silent correctness failures when rebuild pools are constructed via filtering or set operations.

### 3. Initial Schedule Construction

```
current_time = config.work_start
completed = {}
missed = {}

while remaining tasks exist:
    ready = tasks whose depends_on ⊆ completed
    if no ready tasks: cascade-miss remaining (dependency deadlock)
    
    pick highest-priority ready task
    
    end_time = current_time + duration
    fits = (end_time <= work_end) AND (end_time <= deadline if deadline exists)
    
    if fits:
        schedule event at [current_time, end_time]
        completed.add(task_id)
        current_time = end_time
    else:
        missed.add(task_id)
        cascade: any task depending on this is also missed
```

### 4. Emergency Replanning

Process emergencies in chronological `arrival_time` order:

```
for each emergency:
    arrival = parse(emergency.arrival_time)
    
    # Partition current events
    preserved = events where end <= arrival  (these FINISHED)
    interrupted = events where end > arrival  (these are DESTROYED)
    
    # Mark preserved normal tasks as completed
    for evt in preserved:
        if evt is normal task: completed.add(evt.task_id)
    
    # Delete interrupted events from API
    for each API event with end > arrival: delete it
    
    # Insert emergency at arrival time
    insert emergency event at [arrival, arrival + duration]
    
    # Rebuild remaining normal tasks
    interrupted_normal = {evt.task_id for evt in interrupted if normal}
    remaining = interrupted_normal - completed
    
    rebuild schedule from emergency_end using same priority/dependency rules
    mark rebuilt events as "rescheduled"
    insert them into API
```

**Critical invariant**: A task is only "completed" when its event's end time ≤ the current emergency's arrival. Interrupted tasks return to the pool at full duration — no partial credit.

### 5. API Interaction Protocol

```
1. ALWAYS start with: {"cmd":"clear","calendar_id":"..."}
2. Insert events (individually or via batch_insert if available)
3. For emergencies: list → delete interrupted → insert emergency → insert rebuilt
4. ALWAYS call list at least once (e.g., after all inserts) to verify final state
5. Record EVERY request/response in history.jsonl
```

**Critical: Include `status` in Inserted Events.** When inserting events into the API, include the `status` field (`"scheduled"`, `"rescheduled"`, or `"emergency"`). The test compares the remote calendar state (after stripping the internal `id` field) directly with `output.json["schedule"]`. If the inserted events don't include `status`, the remote state won't match the output, causing test failure.

Example:
```json
{"cmd":"insert","calendar_id":"...","event":{"task_id":"A","title":"...","start":"14:00","end":"15:00","status":"scheduled"}}
```

**Critical: Always Call `list`.** The test asserts that `history.jsonl` contains at least one successful `list` call. Always perform a `list` operation after all inserts (and after emergency handling) to verify the final calendar state.

#### Transient Error Handling

If the API returns errors containing "rate limit", "try again", "internal server error", "temporarily", "timeout", or "overloaded": retry the same command up to 10 times with a small delay.

#### Batch Insert Detection

Inspect `api_simulator.py` source for the string `batch_insert`. If present, use:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```
for the initial plan submission. Fall back to individual inserts otherwise.

### 6. Output Format

```json
{
  "schedule": [
    {"task_id": "A", "title": "...", "start": "14:00", "end": "15:00", "status": "scheduled"},
    {"task_id": "EM1", "title": "...", "start": "15:00", "end": "15:30", "status": "emergency"},
    {"task_id": "B", "title": "...", "start": "15:30", "end": "16:15", "status": "rescheduled"}
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

Status values:
- `"scheduled"` — initial plan events
- `"rescheduled"` — events rebuilt after an emergency
- `"emergency"` — emergency events

### 7. History Format

One JSON object per line in `/app/history.jsonl`:
```json
{"request": {"cmd":"insert","calendar_id":"...","event":{...}}, "response": {"status":"ok","event_id":"evt_0"}}
```

## Variation Dimensions

| Dimension | Values | Handling |
|-----------|--------|----------|
| task_volume | 3-12 tasks | Algorithm scales linearly |
| interruption_pattern | none/one/multiple | Loop through emergencies chronologically |
| priority_method | urgency/eisenhower/weighted | Score formula selection |
| scheduling_constraints | deadlines, deps, duplicates | Dependency DAG + deadline checks |
| api_capability | basic/transient-errors/batch | Retry logic + batch detection |

## Edge Cases

1. **Dependency deadlock**: If no ready tasks remain but tasks are uncompleted, cascade-miss all remaining.
2. **Infeasible task**: Duration exceeds available window → mark missed immediately.
3. **Duplicate titles**: Use task_id for identity, not title.
4. **Emergency at work_start**: All events are interrupted; emergency goes first.
5. **Emergency after all tasks complete**: No rebuilding needed; just insert emergency.
6. **Multiple emergencies in quick succession**: Each one rebuilds from its end time.
7. **Task depends on missed task**: Cascade miss to all transitive dependents.

## Execution

```bash
# Copy solver to workspace
cp /skill/solve.py /app/solve.py

# Run
cd /app && python3 solve.py
```

The solver reads `/app/tasks.json` and `/app/api_simulator.py`, computes the schedule, interacts with the simulator, and writes `/app/output.json` and `/app/history.jsonl`.
