---
name: api-scheduler
description: >
  Reusable skill for priority-based task scheduling against a stateful calendar API.
  Handles all family variants: urgency/eisenhower/weighted scoring, dependency DAGs,
  hard deadlines, work-window constraints, emergency replanning with delete+reinsert,
  transient error retry, and batch insertion. Produces a deterministic schedule
  (output.json) and complete API interaction log (history.jsonl).
---

# API Scheduler Skill

## Overview

This skill solves the **api-scheduler** family: given a set of tasks with priorities,
durations, dependencies, and deadlines, build a priority-ordered schedule using a
stateful calendar API, then revise the schedule when emergencies arrive.

## Family Axes Covered

| Axis | Variants | Handling |
|------|----------|----------|
| `task_volume` | 3–12 tasks | Greedy scheduler with principled completed/missed partition |
| `interruption_pattern` | none, 1, or many emergencies | Chronological emergency processing with delete+reinsert |
| `priority_method` | urgency, eisenhower, weighted | Parameterized scoring with deterministic tie-breaking |
| `scheduling_constraints` | work windows, deadlines, deps, duplicates | Dependency-aware greedy loop with deadline enforcement |
| `api_capability` | basic, transient-errors, batch | Retry logic + batch_insert detection from simulator source |

## Core Algorithm

### Priority Scoring

```
urgency:     score = u
eisenhower:  score = u * i
weighted:    score = 0.6*u + 0.4*i            (no team_priority)
weighted:    score = 0.5*u + 0.3*i + 0.2*t    (with team_priority)
```

All scores rounded to 10 decimal places to avoid floating-point comparison issues.

### Tie-Breaking (deterministic)

1. Higher score first
2. Earlier hard deadline wins; task **without** deadline sorts **after** task with one
3. Remaining tie → original input order in `tasks.json`

### Greedy Scheduling Loop

```
1. cursor = work_start
2. While remaining tasks exist:
   a. Find all "ready" tasks (depends_on all in scheduled_ids)
   b. If any ready task has a missed prerequisite → mark it and cascade misses
   c. If no ready tasks but blocked tasks remain → circular deps → mark all missed
   d. Pick highest-priority ready task
   e. If task fits (end ≤ work_end AND end ≤ deadline): schedule, advance cursor
   f. Else: mark missed, don't advance cursor
```

**Critical**: After scheduling each task, re-evaluate the ready set. A newly-scheduled
task may unblock a higher-priority dependent task that should go next.

### Emergency Replanning

For each emergency in chronological `arrival_time` order:

1. **Preserve** events whose `end ≤ arrival_time`
2. **Delete** events whose `end > arrival_time` (including in-progress normal work)
3. **Insert** emergency at exactly `arrival_time`
4. **Rebuild** remaining normal tasks from emergency's `end` time
   - Interrupted normal tasks return to pool at full duration with status "rescheduled"
   - Previously completed tasks stay completed
   - Use same greedy algorithm with cursor at emergency end

### API Contract

- **First mutating call must be `clear`**
- Commands: `clear`, `insert`, `list`, `get`, `delete`, optionally `batch_insert`
- Every request/response logged to `history.jsonl` (including retries)
- Retry transient errors up to 10 times
- Detect `batch_insert` support by inspecting simulator source code
- Final calendar state must exactly match `output.json`

## Usage

```bash
python3 scheduler.py \
  --tasks-file /app/tasks.json \
  --simulator /app/api_simulator.py \
  --history /app/history.jsonl \
  --output /app/output.json
```

## Output Format

```json
{
  "schedule": [
    {"task_id": "A", "title": "...", "start": "14:00", "end": "15:00"},
    {"task_id": "E1", "title": "...", "start": "15:00", "end": "15:30"},
    {"task_id": "B", "title": "...", "start": "15:30", "end": "16:15"}
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

**Critical output format rules:**
- Schedule events contain **exactly** `task_id`, `title`, `start`, `end` — matching the calendar API event structure. **No `status` field.**
- `completion_summary.completed` must be **sorted alphabetically** by task_id.
- Internal status tracking (`scheduled`/`rescheduled`/`emergency`) is used during scheduling and emergency replanning, but **stripped before writing output.json**.
- The final calendar state must exactly match `output.json` schedule (after stripping internal fields).

## Common Failure Modes

1. **Wrong dependency handling**: Must re-evaluate ready set after each scheduling decision
2. **Floating-point tie-breaking**: Round scores to avoid precision issues
3. **Emergency cursor**: Must start rebuilding from emergency end, not from last preserved event
4. **Duplicate events**: Don't include pre-scheduled events in rebuild output
5. **Incomplete history**: Log every API attempt including errors
6. **Missing clear**: First mutating call must be `clear`
7. **Deadline-less tie-break**: Tasks without deadlines sort AFTER tasks with deadlines
8. **Output `status` field**: Schedule events in `output.json` must NOT include `status` — they must match calendar state exactly (only `task_id`, `title`, `start`, `end`). Track status internally for emergency replanning, but strip before serialization.
9. **`completed` not sorted**: `completion_summary.completed` must be `sorted()` alphabetically by task_id, not in schedule/priority order.
