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

## Execution Workflow

1. **Read** `/app/tasks.json`, `/app/simulator_intro.md`, and
   `/app/api_simulator.py` to understand the current variant.
2. **Write** the reference implementation (see §Reference Implementation
   below) to `/app/solve.py`.
3. **Run** `cd /app && rm -f /tmp/calendar_state.json && python3 solve.py`.
4. **Verify** by reading `/app/output.json` and `/app/history.jsonl`.

The `rm -f /tmp/calendar_state.json` step is **critical** — stale simulator
state from a previous run will cause wrong event IDs and duplicate events.

---

## 1 — Input Structure

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
3. Every event needs `task_id`, `title`, `start`, `end`, and `status`.

> **Include `status` in every event sent to the API.**  The grader compares
> calendar state (after stripping the simulator-added `id` field) directly
> against `output.json` schedule entries.  Both must have identical keys:
> `{task_id, title, start, end, status}`.  If you omit `status` from API
> payloads the calendar state will lack it and the comparison will fail.

### Detect batch_insert

Read `/app/api_simulator.py` and look for the string `batch_insert`.  If
present, use it to submit the entire initial plan in one call:

```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```

Each event in the batch must also include `status`.

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

Issue a `delete` call for every event identified in step 5a.  Use the
event's `id` field from the `list` response (e.g. `evt_0`), **not** the
task_id.

### 5c — Insert the emergency

Insert at exactly `arrival_time`.  It must finish by its own deadline (if
present) and by `work_end`.  The event payload uses the same fields
as normal events: `task_id`, `title`, `start`, `end`, `status` (set to
`"emergency"`).

### 5d — Rebuild the remaining plan

- **Completed** = task IDs from preserved events (exclude emergency task IDs).
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

**Remember:** `status` is computed at output time.  It must appear in both
the API event payloads (so the calendar state stores it) and in
`output.json`.

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
   match `output.json` schedule exactly (ignoring the `id` field that the
   simulator adds).
2. **First mutating call was `clear`** — check the first entry in history.
3. **No overlapping events** — all events are chronological and
   non-overlapping.
4. **Dependencies respected** — for every scheduled task, all its
   `depends_on` tasks appear earlier in the schedule.
5. **Deadlines respected** — no event ends after its task's hard deadline.
6. **Emergency ordering** — emergencies processed in `arrival_time` order.
7. **History complete** — every request/response pair is in `history.jsonl`,
   including transient errors.
8. **API events include status** — event payloads sent to insert/batch
   contain `task_id`, `title`, `start`, `end`, `status`.
9. **completed and missed are sorted** — `completion_summary.completed` and
   `completion_summary.missed` are sorted alphabetically by task ID.

## 9 — Variation Axes Reference

| Axis | What changes | How to handle |
|------|-------------|---------------|
| `task_volume` | 3–12 tasks; may not all fit | Greedy naturally partitions completed/missed |
| `interruption_pattern` | 0, 1, or N emergencies | Loop §5 per emergency in arrival order |
| `priority_method` | urgency / eisenhower / weighted | §2 scoring; same algorithm |
| `scheduling_constraints` | deadlines, deps, duplicate titles, infeasible tasks | Cascade-drop on missed deps; deadline check in §3 |
| `api_capability` | basic / transient-errors / batch | Retry on error; detect `batch_insert` in source |

---

## 10 — Reference Implementation

Copy the complete script below into `/app/solve.py` and run it.  It handles
all variation axes: task volume, emergencies, priority methods, dependencies,
deadlines, transient errors, and batch insertion.

```python
#!/usr/bin/env python3
"""General API Scheduler for the api-scheduler family."""
import json, subprocess, os, sys

TASKS_FILE = "/app/tasks.json"
SIMULATOR = "/app/api_simulator.py"
OUTPUT_FILE = "/app/output.json"
HISTORY_FILE = "/app/history.jsonl"
STATE_FILE = "/tmp/calendar_state.json"
history_log = []

def parse_time(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m

def format_time(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"

def api_call(cmd, max_retries=10):
    """Send one JSON command; retry on transient errors. Logs every attempt."""
    cmd_str = json.dumps(cmd) + "\n"
    env = {**os.environ, "SIM_STATE_FILE": STATE_FILE}
    for _ in range(max_retries):
        result = subprocess.run(
            ["python3", SIMULATOR],
            input=cmd_str, capture_output=True, text=True, env=env,
        )
        output = result.stdout.strip()
        if not output:
            continue
        lines = [l for l in output.split("\n") if l.strip()]
        response = json.loads(lines[-1])
        history_log.append({"request": cmd, "response": response})
        if response.get("status") == "ok":
            return response
    raise RuntimeError(f"API call failed after {max_retries} retries: {json.dumps(cmd)}")

def check_batch_support():
    try:
        with open(SIMULATOR) as f:
            return "batch_insert" in f.read()
    except OSError:
        return False

def compute_score(task, method):
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", None)
    if method == "urgency":
        return float(u)
    if method == "eisenhower":
        return float(u * i)
    if method == "weighted":
        if t is not None:
            return 0.5 * u + 0.3 * i + 0.2 * t
        return 0.6 * u + 0.4 * i
    return 0.0

def priority_sort_key(task, method, original_index):
    """Lower tuple = higher priority (sorted ascending)."""
    score = compute_score(task, method)
    deadline = task.get("deadline")
    deadline_val = parse_time(deadline) if deadline else float("inf")
    return (-score, deadline_val, original_index)

def build_schedule(indexed_tasks, config, start_time, completed_ids=frozenset()):
    """Greedy dependency-aware scheduler. Returns (events, missed_ids)."""
    work_end = parse_time(config["work_end"])
    method = config.get("priority_method", "urgency")
    scheduled = []
    missed_ids = set()
    scheduled_ids = set(completed_ids)
    current_time = start_time
    remaining = list(indexed_tasks)

    for _ in range(len(remaining) * 3 + 5):
        if not remaining:
            break
        # Cascade-drop tasks whose deps include a missed task
        clean = []
        for idx, task in remaining:
            deps = task.get("depends_on", [])
            if any(d in missed_ids for d in deps):
                missed_ids.add(task["id"])
            else:
                clean.append((idx, task))
        remaining = clean
        if not remaining:
            break
        # Eligible = all deps satisfied
        eligible = [
            (idx, task) for idx, task in remaining
            if all(d in scheduled_ids for d in task.get("depends_on", []))
        ]
        if not eligible:
            for _, task in remaining:
                missed_ids.add(task["id"])
            break
        # Pick best eligible task
        eligible.sort(key=lambda x: priority_sort_key(x[1], method, x[0]))
        best_idx, best_task = eligible[0]
        remaining = [(i, t) for i, t in remaining if t["id"] != best_task["id"]]
        duration = best_task.get("duration_min", 0)
        end_time = current_time + duration
        deadline = best_task.get("deadline")
        fits = end_time <= work_end
        if deadline:
            fits = fits and end_time <= parse_time(deadline)
        if fits:
            # build_schedule returns bare events; status is added at insert time
            scheduled.append({
                "task_id": best_task["id"],
                "title": best_task["title"],
                "start": format_time(current_time),
                "end": format_time(end_time),
            })
            scheduled_ids.add(best_task["id"])
            current_time = end_time
        else:
            missed_ids.add(best_task["id"])
    return scheduled, missed_ids

def main():
    # Reset simulator state — critical for clean runs
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    with open(TASKS_FILE) as f:
        data = json.load(f)
    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    calendar_id = config["calendar_id"]
    has_batch = check_batch_support()

    # Build initial plan
    indexed_tasks = list(enumerate(tasks))
    init_schedule, missed_ids = build_schedule(
        indexed_tasks, config, parse_time(config["work_start"])
    )

    # Clear calendar (must be first mutating call)
    api_call({"cmd": "clear", "calendar_id": calendar_id})

    # Insert initial events (include status so calendar state matches output)
    if has_batch and init_schedule:
        api_call({
            "cmd": "batch_insert", "calendar_id": calendar_id,
            "events": [
                {"task_id": e["task_id"], "title": e["title"],
                 "start": e["start"], "end": e["end"],
                 "status": "scheduled"}
                for e in init_schedule
            ],
        })
    else:
        for evt in init_schedule:
            api_call({
                "cmd": "insert", "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"], "title": evt["title"],
                    "start": evt["start"], "end": evt["end"],
                    "status": "scheduled",
                },
            })

    # Tracking sets for status labels
    ever_rescheduled = set()
    emergency_ids = set()

    # Process emergencies chronologically
    emergencies.sort(key=lambda e: parse_time(e["arrival_time"]))
    for emergency in emergencies:
        arrival = parse_time(emergency["arrival_time"])
        resp = api_call({"cmd": "list", "calendar_id": calendar_id})
        current_events = resp.get("events", [])

        # Partition: preserved vs to-delete
        preserved = [e for e in current_events if parse_time(e["end"]) <= arrival]
        to_delete = [e for e in current_events if parse_time(e["end"]) > arrival]

        # Delete future/overlapping events using their event id
        for evt in to_delete:
            api_call({
                "cmd": "delete", "calendar_id": calendar_id,
                "event_id": evt["id"],
            })

        # Insert emergency
        em_duration = emergency.get("duration_min", 0)
        em_end = arrival + em_duration
        em_task_id = emergency.get("id", emergency.get("task_id", "emergency"))
        api_call({
            "cmd": "insert", "calendar_id": calendar_id,
            "event": {
                "task_id": em_task_id, "title": emergency["title"],
                "start": format_time(arrival), "end": format_time(em_end),
                "status": "emergency",
            },
        })
        emergency_ids.add(em_task_id)

        # Completed = preserved normal tasks (not emergencies)
        completed_ids = set()
        for evt in preserved:
            tid = evt.get("task_id")
            if tid and tid not in emergency_ids:
                completed_ids.add(tid)

        # Rebuild remaining plan from emergency end time
        remaining_tasks = [
            (idx, task) for idx, task in enumerate(tasks)
            if task["id"] not in completed_ids
        ]
        new_schedule, missed_ids = build_schedule(
            remaining_tasks, config, em_end, completed_ids
        )
        for evt in new_schedule:
            api_call({
                "cmd": "insert", "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"], "title": evt["title"],
                    "start": evt["start"], "end": evt["end"],
                    "status": "rescheduled",
                },
            })
            ever_rescheduled.add(evt["task_id"])

    # Assemble final output from calendar state
    resp = api_call({"cmd": "list", "calendar_id": calendar_id})
    final_events = resp.get("events", [])

    def get_status(task_id):
        if task_id in emergency_ids:
            return "emergency"
        if task_id in ever_rescheduled:
            return "rescheduled"
        return "scheduled"

    schedule_out = []
    for evt in final_events:
        tid = evt.get("task_id", "")
        schedule_out.append({
            "task_id": tid, "title": evt.get("title", ""),
            "start": evt.get("start", ""), "end": evt.get("end", ""),
            "status": evt.get("status", get_status(tid)),
        })
    schedule_out.sort(key=lambda e: parse_time(e["start"]))

    # Completion summary: normal tasks only, SORTED alphabetically
    completed = sorted(
        e["task_id"] for e in schedule_out
        if e["status"] in ("scheduled", "rescheduled")
    )
    all_normal_ids = [t["id"] for t in tasks]
    missed = sorted(tid for tid in all_normal_ids if tid not in set(completed))

    output = {
        "schedule": schedule_out,
        "completion_summary": {
            "completed": completed,
            "missed": missed,
            "total_tasks": len(tasks),
            "completed_count": len(completed),
            "missed_count": len(missed),
        },
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    with open(HISTORY_FILE, "w") as f:
        for entry in history_log:
            f.write(json.dumps(entry) + "\n")
    print(f"Schedule: {len(completed)} completed, {len(missed)} missed")
    print(f"  Completed: {completed}")
    print(f"  Missed:    {missed}")

if __name__ == "__main__":
    main()
```
