---
name: api-scheduler
description: >
  Use a stateful calendar API simulator to build a priority-based task schedule,
  handle emergency interruptions with stateful replanning, and produce correct
  output artifacts. Covers priority scoring (urgency/eisenhower/weighted),
  dependency-aware scheduling, emergency deletion and rescheduling, transient
  error retries, optional batch insertion, and full API interaction logging.
---

# API Scheduler Skill

## Overview

You are a product manager scheduling tasks within a work-day window using a
calendar API simulator. The simulator reads JSON commands from stdin (one per
line) and writes JSON responses to stdout. State persists across invocations
via a temp file. You must:

1. Read configuration from `/app/tasks.json`
2. Read API documentation from `/app/simulator_intro.md`
3. Inspect `/app/api_simulator.py` for hidden capabilities (e.g. batch_insert)
4. Build a priority-ordered schedule respecting constraints
5. Submit the plan via the API, handling emergencies and errors
6. Record **every** API request/response pair in `/app/history.jsonl`
7. Write the final schedule to `/app/output.json`

## Step 1: Read and Parse Inputs

Read `/app/tasks.json`. It contains:
- `tasks`: array of task objects with fields like `id`, `title`, `duration_min`,
  `urgency`, `importance`, optionally `team_priority`, `depends_on` (list of
  task IDs), `deadline` (HH:MM string or null)
- `emergencies`: array of emergency objects (may be empty) with `id`, `title`,
  `duration_min`, `arrival_time`, optionally `deadline`
- `config`: `work_start`, `work_end`, `priority_method`, `calendar_id`

Read `/app/simulator_intro.md` for the full scheduling contract.

Read `/app/api_simulator.py` source code to check if `batch_insert` is
supported. Look for the string `"batch_insert"` in the source. If present,
you can use batch insertion for the initial plan; otherwise use individual
`insert` commands.

## Step 2: Compute Priority Scores

Use the `priority_method` from config:

| Method     | Formula                                                    |
|------------|------------------------------------------------------------|
| urgency    | `score = urgency`                                          |
| eisenhower | `score = urgency * importance`                             |
| weighted   | `score = 0.6*u + 0.4*i` (no team_priority field present)  |
| weighted   | `score = 0.5*u + 0.3*i + 0.2*t` (team_priority present)   |

**Tie-breaking (deterministic):**
1. Higher score first
2. Earlier hard deadline first (tasks **without** a deadline sort **after**
   those with one)
3. Original input order in `tasks.json` (earlier index first)

## Step 3: Build the Initial Plan

**Algorithm — greedy priority scheduling with dependencies:**

```
available_time = parse_time(config.work_start)
work_end = parse_time(config.work_end)
scheduled = []
missed = []
completed_ids = set()

Repeat until all tasks are processed:
  candidates = tasks not yet scheduled or missed
               whose depends_on tasks are all in completed_ids
  if no candidates: break (remaining tasks have unresolvable deps → missed)

  Sort candidates by priority (descending) with tie-breaking rules.
  Pick the top candidate.

  start = available_time
  end = start + duration_min

  Feasibility checks:
    - end <= work_end
    - If task has a deadline: end <= parse_time(deadline)

  If feasible:
    scheduled.append(task with start, end, status="scheduled")
    completed_ids.add(task.id)
    available_time = end
  Else:
    missed.append(task)
    # Do NOT add to completed_ids — dependents will also be missed
```

**Critical rules:**
- A task whose prerequisite is missed is automatically missed.
- Events are uninterrupted blocks (no splitting).
- Time is tracked in minutes from midnight for arithmetic.

## Step 4: Submit the Initial Plan to the API

**The first mutating request MUST be `clear`.**

Build a helper script (see scripts section below) or use inline commands.

For each event in the initial plan:
```json
{"cmd":"insert","calendar_id":"...","event":{"task_id":"A","title":"...","start":"14:00","end":"15:00"}}
```

If batch_insert is available in the simulator, use:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

Record every request and response in `/app/history.jsonl`:
```json
{"request":{...},"response":{...}}
```

## Step 5: Handle Emergencies

Process emergencies in chronological `arrival_time` order. For each:

1. **Preserve** calendar events whose `end` ≤ `arrival_time`.
2. **Delete** every event whose `end` > `arrival_time` (including in-progress).
   - Use `{"cmd":"delete","calendar_id":"...","event_id":"evt_N"}` for each.
   - Interrupted normal tasks return to the pool at full duration (no partial credit).
3. **Insert** the emergency event at exactly `arrival_time`.
   - Emergency must finish by its deadline (if any) and by `work_end`.
   - Status = `"emergency"`.
4. **Rebuild** the remaining normal plan starting from the emergency's end time.
   - Use the same priority + dependency algorithm from Step 3.
   - Rescheduled events get status = `"rescheduled"`.
   - Submit new events via insert (or batch_insert if available).
5. Repeat for later emergencies.

**Important:** When deleting, you need the `event_id` for each calendar event.
Use `list` or track IDs from insert responses. After deletions and re-insertions,
event IDs increment — always track them.

## Step 6: Handle API Errors

- If a response has `status: "error"`, the state was **not** mutated.
- For transient errors (rate limiting, server errors), **retry the same
  logical operation** until it succeeds.
- Record every attempt (including failed ones) in `history.jsonl`.
- Use a retry loop with a reasonable max (e.g., 20 retries).

## Step 7: Write Output

Write `/app/output.json`:

```json
{
  "schedule": [
    {"task_id": "A", "title": "...", "start": "14:00", "end": "15:00", "status": "scheduled"},
    {"task_id": "F", "title": "Emergency Fix", "start": "15:30", "end": "16:00", "status": "emergency"},
    {"task_id": "B", "title": "...", "start": "16:00", "end": "16:45", "status": "rescheduled"}
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

- `schedule` must be chronological and non-overlapping.
- `schedule` includes all events: normal tasks, emergencies, and rescheduled tasks.
- `completed` lists only **normal** tasks that were successfully scheduled.
- `missed` lists only **normal** tasks that could not be scheduled.
- `total_tasks` counts normal tasks only (not emergencies).
- Invariant: `completed_count + missed_count == total_tasks`.
- Statuses: `scheduled` (initial plan), `rescheduled` (after emergency),
  `emergency` (emergency event).

## Helper Script

Use the provided `scripts/schedule.py` to automate the entire workflow.
Invoke it with:

```bash
python3 /app/scripts/schedule.py
```

It reads `/app/tasks.json`, computes the schedule, interacts with the API
simulator, and writes all output files. If you need to adapt behavior (e.g.,
different priority methods), the script handles all variants.

## Time Arithmetic

Use minutes-from-midnight for all calculations:
- `"14:00"` → 840
- `"15:30"` → 930
- To add duration: `end_min = start_min + duration_min`
- To format back: `f"{h:02d}:{m:02d}"` where `h, m = divmod(total_min, 60)`

## Verification Checklist

Before finalizing, verify:

1. ✅ First mutating API call was `clear`
2. ✅ All events are chronological and non-overlapping
3. ✅ Every event has `task_id`, `title`, `start`, `end`
4. ✅ All events fit within `[work_start, work_end]`
5. ✅ Tasks with deadlines end by their deadline
6. ✅ Dependencies are respected (prereq completes before dependent starts)
7. ✅ Emergency events start at their `arrival_time`
8. ✅ Events ending after an emergency arrival were deleted
9. ✅ `history.jsonl` has every request/response pair (including retries)
10. ✅ Final `list` command confirms simulator state matches `output.json`
11. ✅ `output.json` has correct `completion_summary` counts
12. ✅ Status values are correct (`scheduled`/`rescheduled`/`emergency`)
