---
name: api-scheduler
description: >
  Build a priority-based schedule using a stateful calendar API simulator,
  then revise the remote state when emergencies invalidate the plan.
  Handles urgency/eisenhower/weighted scoring, dependency DAGs, hard deadlines,
  transient errors, batch insertion, and chronological emergency replanning.
---

# API Scheduler Skill

## Overview

This skill solves scheduling tasks that require:
1. Reading a task list with priorities, durations, deadlines, and dependencies
2. Computing a deterministic priority order
3. Building a greedy schedule within a work window
4. Submitting events to a stateful calendar API (simulator)
5. Replanning when emergencies arrive (delete future events, insert emergency, reschedule remaining)
6. Logging every API interaction and writing a final output

## Input Format

Read `/app/tasks.json`:
```json
{
  "tasks": [
    {
      "id": "A",
      "title": "...",
      "duration_min": 60,
      "urgency": 5,
      "importance": 3,
      "team_priority": 2,     // optional, only for weighted method
      "deadline": "17:00",    // optional hard deadline
      "depends_on": ["B"]     // optional dependency list
    }
  ],
  "emergencies": [
    {
      "id": "EM1",
      "title": "Server Down",
      "arrival_time": "15:30",
      "duration_min": 30,
      "deadline": "16:00"     // optional
    }
  ],
  "config": {
    "work_start": "14:00",
    "work_end": "19:00",
    "priority_method": "urgency",  // urgency | eisenhower | weighted
    "calendar_id": "..."
  }
}
```

## Priority Scoring (Deterministic)

Given urgency `u`, importance `i`, team_priority `t`:

| Method | Formula |
|--------|---------|
| `urgency` | `score = u` |
| `eisenhower` | `score = u * i` |
| `weighted` (no team_priority) | `score = 0.6*u + 0.4*i` |
| `weighted` (with team_priority) | `score = 0.5*u + 0.3*i + 0.2*t` |

**Tie-breaking** (applied in order):
1. Higher score first
2. Earlier hard deadline first (task without deadline sorts after one with deadline)
3. Earlier position in the original `tasks.json` array

## Initial Plan Algorithm

Greedy scheduling starting at `config.work_start`:

1. Maintain a set of `completed_ids` (initially empty) and `remaining` tasks.
2. Find all tasks whose `depends_on` are all in `completed_ids`.
3. Sort ready tasks by priority (descending score, then deadline, then original index).
4. Pick the highest-priority ready task.
5. If it fits (ends by both its deadline and `work_end`): schedule it, add to completed, advance clock.
6. Otherwise: mark it **missed** and cascade — any task that depends on a missed task is also missed.
7. Repeat until no remaining tasks.

**Key invariant**: Previously-missed tasks are never reconsidered after emergencies (emergencies consume time, never free it).

## Simulator Interaction

The simulator at `/app/api_simulator.py` reads JSON from stdin, one command per line.

### Required sequence:
1. **`clear`** — first successful mutating request must be clear
2. **`insert`** — one event at a time (or `batch_insert` if supported)
3. **`list`** — verify final state matches output

### Commands:
```json
{"cmd":"clear","calendar_id":"..."}
{"cmd":"insert","calendar_id":"...","event":{"task_id":"A","title":"...","start":"14:00","end":"15:00","status":"scheduled"}}
{"cmd":"delete","calendar_id":"...","event_id":"evt_0"}
{"cmd":"list","calendar_id":"..."}
{"cmd":"get","calendar_id":"...","event_id":"evt_0"}
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

**Critical**: All insert operations must include the `status` field in the event dict. The simulator stores whatever fields you provide, and tests verify that the remote state exactly matches `output.json` (after stripping the auto-generated `id` field). If you omit `status` from inserts, the remote state won't match your output and tests will fail.

- Initial plan events: `"status": "scheduled"`
- Emergency events: `"status": "emergency"`
- Rescheduled events (after emergency): `"status": "rescheduled"`

### Batch insertion detection:
Inspect `api_simulator.py` source for `"batch_insert"`. If present, use batch for initial plan insertion. Each event in the batch must include the `status` field:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[
  {"task_id":"A","title":"...","start":"14:00","end":"15:00","status":"scheduled"},
  {"task_id":"B","title":"...","start":"15:00","end":"15:45","status":"scheduled"}
]}
```

### Transient error handling:
If response has `status: "error"` with message containing "rate limit", "internal server error", or "try again", retry the same request (up to 10 times).

## Emergency Replanning

Process emergencies in chronological `arrival_time` order. For each:

1. **Preserve** calendar events whose `end <= arrival_time`.
2. **Delete** every event whose `end > arrival_time` (including in-progress). Interrupted work gets no partial credit and returns to the remaining-task pool at full duration.
3. **Insert** the emergency at exactly its `arrival_time` with `"status": "emergency"`. It must finish by its deadline (if present) and by `work_end`.
4. **Rebuild** remaining normal plan starting at the emergency's end time, using the same dependency and priority rules. Insert these events with `"status": "rescheduled"`.

Repeat for each subsequent emergency.

## Output Format

### `/app/output.json`:
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
- `"scheduled"` — normal events in the initial plan
- `"rescheduled"` — normal events placed after an emergency
- `"emergency"` — emergency events

**Important**: The `completed` and `missed` lists in `completion_summary` must be **sorted alphabetically by task_id**. Tests compare these against `sorted(expected_ids)`, so order matters.

### `/app/history.jsonl`:
One JSON object per line, **every** API attempt including errors:
```json
{"request":{"cmd":"clear","calendar_id":"..."},"response":{"status":"ok","message":"..."}}
{"request":{"cmd":"insert",...},"response":{"status":"ok","event_id":"evt_0"}}
```

## Execution

Copy `scripts/scheduler.py` to `/app/scheduler.py` and run:
```bash
rm -f /tmp/calendar_state.json
cd /app && python3 scheduler.py
```

The script handles the full pipeline: read input → compute priorities → build schedule → interact with API → handle emergencies → write output and history.

## Variation Dimensions

This skill covers the full `api-scheduler` family:
- **task_volume**: 3–12 tasks, including cases where all fit and cases requiring missed partitioning
- **interruption_pattern**: none, one emergency, or multiple chronological emergencies
- **priority_method**: urgency, eisenhower, weighted (with/without team_priority)
- **scheduling_constraints**: work windows, hard deadlines, dependency DAGs, infeasible requirements, duplicate titles, API errors
- **api_capability**: basic insert, transient errors (retry), batch insertion
