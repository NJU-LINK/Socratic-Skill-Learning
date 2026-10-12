---
name: api-scheduler
description: Build a priority-based schedule using a stateful calendar API, handle emergencies that invalidate planned events, and produce a verified output with full API history.
---

# API Scheduler Skill

## Overview

You are a product manager with a work window (e.g., 14:00–19:00) and a list of tasks to schedule. You must interact with a stateful calendar API simulator to build a priority-ordered schedule, handle emergencies that disrupt the plan, and produce verified output files.

This skill handles the full **api-scheduler** family, which varies along these dimensions:
- **task_volume**: 3–12 tasks, including cases where all fit and cases requiring a completed/missed partition
- **interruption_pattern**: no emergencies, one emergency, or multiple chronological emergencies
- **priority_method**: urgency, eisenhower, or weighted (with optional team_priority)
- **scheduling_constraints**: work windows, hard deadlines, dependency DAGs, infeasible requirements, duplicate titles, API errors
- **api_capability**: basic (individual inserts), transient-errors (retryable failures), or batch (batch_insert command)

## Execution Procedure

### 1. Copy the solver script to /app

```bash
cp /skill/scripts/solve.py /app/solve.py
```

### 2. Run the solver

```bash
python3 /app/solve.py
```

The script handles everything: reading inputs, computing priorities, scheduling, API interaction, emergency replanning, history logging, and output generation.

### 3. Verify outputs

Check that `/app/output.json` contains:
- `schedule`: array of events with `task_id`, `title`, `start`, `end` (NO status field — must match simulator state exactly)
- `completion_summary`: `completed` (sorted), `missed` (sorted), `total_tasks`, `completed_count`, `missed_count`

Check that `/app/history.jsonl` contains one JSON object per line: `{"request":{...},"response":{...}}`

Verify the simulator state matches output:
```bash
echo '{"cmd":"list","calendar_id":"..."}' | python3 /app/api_simulator.py
```

## Core Algorithm

### Priority Scoring

Given urgency `u`, importance `i`, and optional team_priority `t`:

- **urgency**: score = `u`
- **eisenhower**: score = `u * i`
- **weighted** without `team_priority`: score = `0.6*u + 0.4*i`
- **weighted** with `team_priority`: score = `0.5*u + 0.3*i + 0.2*t`

Higher scores come first. Tie-breaking (in order):
1. Earlier hard deadline first
2. Task without deadline sorts after task with deadline
3. Input order in `tasks.json`

### Initial Scheduling

Start at `config.work_start`. Greedily place tasks:

1. Sort remaining tasks by priority (highest first)
2. Pick the highest-priority task whose `depends_on` tasks are all completed
3. Schedule it at the current cursor time if:
   - It finishes by its hard deadline (when present)
   - It finishes by `config.work_end`
4. If it doesn't fit, mark it missed and continue
5. If a prerequisite is missed, cascade: all tasks depending on it are also missed
6. Repeat until all tasks are scheduled or missed

### Emergency Replanning

Process emergencies in chronological `arrival_time` order. For each emergency:

1. **Preserve** events whose `end` ≤ arrival_time
2. **Delete** events whose `end` > arrival_time (including in-progress events). Interrupted work returns to the task pool at full duration.
3. **Insert** the emergency at exactly its arrival_time. It must finish by its deadline (when present) and by work_end.
4. **Rebuild** the remaining normal-task plan starting at the emergency's end time:
   - Remaining tasks = interrupted tasks + previously missed tasks
   - Use the same priority and dependency rules

### Event Status Tracking (Internal Only)

Track status internally to determine completed vs missed:
- `"scheduled"`: normal events from the initial plan
- `"rescheduled"`: normal events created after an emergency
- `"emergency"`: emergency events

**Important**: The `status` field is NOT included in the output `schedule` array. The schedule must match the simulator state exactly (which has no status field). Status is used only internally to determine which tasks go into `completed` vs `missed`.

## API Interaction

### Simulator Protocol

The simulator at `/app/api_simulator.py` reads JSON commands from stdin (one per line) and writes JSON responses. State persists via `/tmp/calendar_state.json`.

**Required commands:**
```json
{"cmd":"clear","calendar_id":"..."}
{"cmd":"insert","calendar_id":"...","event":{"task_id":"A","title":"...","start":"14:00","end":"15:00"}}
{"cmd":"list","calendar_id":"..."}
{"cmd":"get","calendar_id":"...","event_id":"evt_0"}
{"cmd":"delete","calendar_id":"...","event_id":"evt_0"}
```

**Critical requirements:**
- The first mutating request MUST be `clear`
- Every event must have: `task_id`, `title`, `start`, `end`
- Record EVERY request/response pair in `history.jsonl`
- Final simulator state must exactly match `output.json` schedule (no status field)

### Batch Insert Detection

Some variants expose a `batch_insert` command. Detect it by inspecting `/app/api_simulator.py`:

```python
def has_batch_insert():
    with open("/app/api_simulator.py") as f:
        return "batch_insert" in f.read()
```

If available, submit the initial plan in ONE call:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

Otherwise, use individual `insert` calls.

### Transient Error Handling

Some variants inject transient errors (rate limits, internal server errors). Retry the same logical operation until it succeeds:

```python
def call_sim(cmd_dict, max_retries=10):
    for attempt in range(max_retries):
        # Send command, get response
        if response["status"] == "ok":
            return response
        elif "Rate limit" in response.get("message", "") or "Internal server error" in response.get("message", ""):
            time.sleep(0.1)
            continue  # retry
        else:
            return response  # permanent error
    return {"status": "error", "message": "Max retries exceeded"}
```

Record every attempt (including errors) in `history.jsonl`.

## Output Format

Write `/app/output.json`:
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

**Critical**: 
- Schedule events have NO `status` field (must match simulator state exactly)
- `completed` = sorted task_ids from schedule (includes emergencies that were scheduled)
- `missed` = complement of completed against all_task_ids (normal + emergency task IDs)
- `total_tasks` = len(all_task_ids) — includes both normal and emergency tasks
- Schedule is sorted by `(start, task_id)` to match test expectations
- Events are chronological and non-overlapping

## Common Pitfalls

1. **Forgetting to clear first**: The first mutating command must be `clear`
2. **Missing task_id in events**: Every event must have `task_id`, `title`, `start`, `end`
3. **Including status in schedule**: The schedule must NOT have a `status` field — it must match simulator state exactly
4. **Not sorting completed/missed**: Both lists must be sorted; `completed` = sorted(schedule task_ids), `missed` = sorted(all_task_ids - completed)
5. **Not handling dependencies**: If a prerequisite is missed, all dependents are missed
6. **Incorrect emergency deletion**: Delete events where `end > arrival_time`, not `start >= arrival_time`
7. **Not retrying transient errors**: Loop until success or max retries
8. **Not recording all API calls**: Every request/response pair goes in `history.jsonl`
9. **Mismatched state**: Final simulator state (via `list`) must match `output.json` schedule

## Testing Your Solution

After running the solver:
1. Check `output.json` has correct schedule (no status) and summary (sorted lists)
2. Check `history.jsonl` has all API exchanges
3. Verify simulator state with `list` command matches output schedule
4. Ensure all tasks are accounted for (completed + missed = total_tasks)
