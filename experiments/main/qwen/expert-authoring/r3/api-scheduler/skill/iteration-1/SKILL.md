---
name: api-scheduler
description: >
  Build a priority-based schedule against a stateful calendar API simulator,
  then revise the remote state when emergencies or API errors invalidate the
  plan. Covers urgency/eisenhower/weighted scoring, dependency DAGs, hard
  deadlines, transient-error retries, batch insertion, and multi-emergency
  replanning.
---

# API Scheduler

You are a product manager who must schedule tasks into a work-day calendar by
interacting with a JSON-line calendar API simulator.  The task list, work
window, priority method, and any emergencies come from `/app/tasks.json`.  The
API contract lives in `/app/simulator_intro.md`; the simulator itself is at
`/app/api_simulator.py`.

## Quick Start

A complete reference implementation is at `scripts/scheduler.py`.  For most
variants you can run it directly:

```bash
python3 scripts/scheduler.py
```

If you need to adapt the logic (e.g., novel constraints discovered at runtime),
read the decision rules below and modify accordingly.

---

## 1 — Read Inputs

| File | Purpose |
|------|---------|
| `/app/tasks.json` | Tasks, optional emergencies, config block |
| `/app/simulator_intro.md` | Full API contract and scheduling rules |
| `/app/api_simulator.py` | Simulator source — inspect for hidden commands |

Key fields in `tasks.json`:

```
tasks[]:       id, title, duration_min, urgency, importance,
               [team_priority], [deadline], [depends_on]
emergencies[]: id|task_id, title, duration_min, arrival_time, [deadline]
config:        work_start, work_end, priority_method, calendar_id
```

## 2 — Priority Scoring

| Method | Formula |
|--------|---------|
| `urgency` | `score = urgency` |
| `eisenhower` | `score = urgency × importance` |
| `weighted` (no team_priority) | `score = 0.6·u + 0.4·i` |
| `weighted` (with team_priority) | `score = 0.5·u + 0.3·i + 0.2·t` |

**Tie-breaking (all methods):**
1. Higher score first.
2. Earlier hard deadline first.  A task *without* a deadline sorts **after**
   every task that has one.
3. Input order in `tasks.json` (earlier index wins).

Distinct task IDs remain distinct even when their titles are identical — always
key on `id`, never on `title`.

## 3 — Build the Initial Plan

Greedy, dependency-aware algorithm starting at `config.work_start`:

```
while unscheduled tasks remain:
    1. Cascade-drop any task whose depends_on includes a missed task.
    2. Eligible = tasks whose every dependency is already scheduled.
       If none are eligible, all remaining are missed → stop.
    3. Pick the eligible task with the best priority (lowest sort key).
    4. If (current_time + duration ≤ work_end) AND
          (no deadline OR current_time + duration ≤ deadline):
         → schedule it, advance current_time.
       Else:
         → mark it missed (cascades in step 1 next iteration).
```

**Do not** reserve slack for future emergencies.

## 4 — Submit to the Calendar API

### Interaction model

The simulator reads one JSON command per line from **stdin** and writes one
JSON response per line to **stdout**.  State persists across invocations via a
temp file (default `/tmp/calendar_state.json`).

### Required sequence

1. **Clear** — must be the first mutating call.
2. **Insert** each event (or **batch_insert** if the simulator supports it).
3. Every event needs `task_id`, `title`, `start`, `end`.

### Detect batch_insert

Read `/app/api_simulator.py` and look for the string `batch_insert`.  If
present, use it to submit the entire initial plan in one call:

```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

### Transient-error retry

When a response has `"status": "error"`, retry the **same logical operation**
until it succeeds.  Record every attempt (including errors) in `history.jsonl`.

## 5 — Process Emergencies

Emergencies arrive in chronological `arrival_time` order.  For each one:

### 5a — Preserve completed work

List calendar events.  Any event whose `end ≤ arrival_time` is **preserved**
(it is already done).  Every other event (`end > arrival_time`, including
in-progress work) must be **deleted** — no partial credit.

### 5b — Delete future events

Issue a `delete` call for every event identified in step 5a.

### 5c — Insert the emergency

Insert at exactly `arrival_time`.  It must finish by its own deadline (if
present) and by `work_end`.

### 5d — Rebuild the remaining plan

- **Completed** = task IDs from preserved events.
- **Remaining** = all normal tasks not in completed.
- Run the same greedy algorithm from §3 starting at the emergency's end time,
  seeding `completed_ids` with the preserved set.
- Submit the new events via `insert`.

### 5e — Repeat for later emergencies

Each subsequent emergency sees the full current calendar state (preserved +
emergency + rescheduled events) and repeats steps 5a–5d.

## 6 — Status Labels

| Condition | `status` value |
|-----------|---------------|
| Normal event from the initial plan (never deleted) | `"scheduled"` |
| Normal event created after any emergency | `"rescheduled"` |
| Emergency event | `"emergency"` |

A task that was in the initial plan, preserved through an emergency, and never
re-inserted keeps `"scheduled"`.  A task deleted and later re-scheduled becomes
`"rescheduled"`.

## 7 — Write Output Files

### `/app/output.json`

```json
{
  "schedule": [
    {"task_id":"A","title":"...","start":"14:00","end":"15:00","status":"scheduled"}
  ],
  "completion_summary": {
    "completed": ["A"],
    "missed":    ["B"],
    "total_tasks": 2,
    "completed_count": 1,
    "missed_count": 1
  }
}
```

- `schedule` lists **all** calendar events (normal + emergency), sorted
  chronologically.
- `completion_summary` covers **normal tasks only** (emergencies excluded).
- `total_tasks = completed_count + missed_count`.

### `/app/history.jsonl`

One JSON object per line, recording every API attempt:

```json
{"request":{...},"response":{...}}
```

Include retries and error responses — the grader checks that all attempts are
logged.

## 8 — Verification Checklist

Before declaring done, verify:

1. **Calendar state matches output** — run `list` and confirm the events
   match `output.json` schedule exactly.
2. **First mutating call was `clear`** — check the first entry in history.
3. **No overlapping events** — all events are chronological and
   non-overlapping.
4. **Dependencies respected** — for every scheduled task, all its
   `depends_on` tasks appear earlier in the schedule.
5. **Deadlines respected** — no event ends after its task's hard deadline.
6. **Emergency ordering** — emergencies processed in `arrival_time` order.
7. **History complete** — every request/response pair is in `history.jsonl`,
   including transient errors.

## 9 — Variation Axes Reference

| Axis | What changes | How to handle |
|------|-------------|---------------|
| `task_volume` | 3–12 tasks; may not all fit | Greedy naturally partitions completed/missed |
| `interruption_pattern` | 0, 1, or N emergencies | Loop §5 per emergency in arrival order |
| `priority_method` | urgency / eisenhower / weighted | §2 scoring; same algorithm |
| `scheduling_constraints` | deadlines, deps, duplicate titles, infeasible tasks | Cascade-drop on missed deps; deadline check in §3 |
| `api_capability` | basic / transient-errors / batch | Retry on error; detect `batch_insert` in source |
