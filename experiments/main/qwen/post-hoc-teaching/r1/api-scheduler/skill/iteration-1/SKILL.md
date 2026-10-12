---
name: api-scheduler
description: >
  Build a priority-based schedule from tasks.json, submit it to a stateful
  calendar API simulator, handle emergency replanning, and produce output.json
  plus a full history.jsonl of all API interactions. Covers urgency/eisenhower/weighted
  priority methods, dependency DAGs, hard deadlines, transient API errors, and
  batch insertion when available.
---

# API Scheduler Skill

## Overview

This skill solves calendar-scheduling tasks where an agent must:
1. Read tasks and configuration from `/app/tasks.json`
2. Read the API contract from `/app/simulator_intro.md`
3. Inspect `/app/api_simulator.py` for available commands (especially `batch_insert`)
4. Compute a priority-ordered schedule
5. Submit events to the calendar API via stdin/stdout JSON
6. Handle emergencies by deleting and rescheduling
7. Write `/app/output.json` and `/app/history.jsonl`

## Step-by-Step Procedure

### 1. Load Inputs

Read `/app/tasks.json` to extract:
- `tasks`: array of task objects with `id`, `title`, `duration_min`, `urgency`, `importance`, optionally `team_priority`, `deadline` (HH:MM), `depends_on` (list of task IDs)
- `emergencies`: array of emergency objects with `id`, `title`, `duration_min`, `arrival_time` (HH:MM), optionally `deadline`
- `config`: object with `work_start`, `work_end`, `priority_method`, `calendar_id`

Read `/app/simulator_intro.md` for the full scheduling contract.

Inspect `/app/api_simulator.py` to check:
- Whether `batch_insert` command is supported (look for `elif action == "batch_insert"` or similar)
- Whether transient error injection is configured (`error_rate`, `rate_limit`)
- Any additional commands beyond the basic set

### 2. Compute Priority Scores

Based on `config.priority_method`:

| Method | Formula |
|--------|---------|
| `urgency` | `score = urgency` |
| `eisenhower` | `score = urgency * importance` |
| `weighted` (no team_priority) | `score = 0.6*urgency + 0.4*importance` |
| `weighted` (with team_priority) | `score = 0.5*urgency + 0.3*importance + 0.2*team_priority` |

**Tie-breaking** (applied in order):
1. Higher score first
2. Earlier hard deadline first (task without deadline sorts AFTER task with deadline)
3. Earlier position in `tasks.json` (input order)

### 3. Build Initial Schedule

Algorithm (greedy, dependency-aware):

```
current_time = parse(config.work_start)  # in minutes from midnight
scheduled = []    # list of (task_id, start, end, status)
completed_ids = set()
missed_ids = set()
remaining = list of all normal tasks

while remaining is not empty:
    # Find eligible tasks: all depends_on tasks are in completed_ids or scheduled earlier
    eligible = [t for t in remaining if all deps satisfied]
    
    if no eligible tasks:
        # All remaining tasks have unsatisfied deps -> mark all as missed
        for t in remaining:
            missed_ids.add(t.id)
        break
    
    # Sort eligible by priority (score desc, deadline asc, input order asc)
    sort eligible by priority
    
    task = eligible[0]
    
    # Check if task can finish by its deadline and work_end
    end_time = current_time + task.duration_min
    deadline_ok = (task has no deadline) or (end_time <= parse(task.deadline))
    work_ok = end_time <= parse(config.work_end)
    
    if deadline_ok and work_ok:
        schedule task at [current_time, end_time) with status "scheduled"
        current_time = end_time
        completed_ids.add(task.id)
        remove task from remaining
    else:
        # Task cannot fit -> mark as missed
        missed_ids.add(task.id)
        remove task from remaining
        # Cascade: any task depending on this one is also missed
        cascade_miss(task.id, remaining, missed_ids)

```

**Dependency cascade**: If a task is missed, all tasks that depend on it (transitively) are also missed.

```python
def cascade_miss(missed_id, remaining, missed_ids):
    """Remove all tasks that transitively depend on missed_id.
    
    Checks against the full missed_ids set (not just missed_id) so that
    chains like A→B→C are fully cascaded: when B is added to missed_ids,
    the next iteration finds C because C depends on B which is now in missed_ids.
    """
    missed_ids.add(missed_id)
    changed = True
    while changed:
        changed = False
        to_remove = []
        for t in remaining:
            if any(d in missed_ids for d in t.get('depends_on', [])):
                to_remove.append(t)
        for t in to_remove:
            remaining.remove(t)
            missed_ids.add(t['id'])
            changed = True
```

### 4. Submit to API

**Always start with `clear`** as the first mutating command.

```python
# Basic approach - one insert at a time
send: {"cmd": "clear", "calendar_id": calendar_id}
for each event in schedule:
    send: {"cmd": "insert", "calendar_id": calendar_id, "event": {
        "task_id": task_id,
        "title": title,
        "start": HH:MM,
        "end": HH:MM
    }}
    record request and response in history

# Batch approach (if api_simulator.py supports batch_insert)
send: {"cmd": "clear", "calendar_id": calendar_id}
send: {"cmd": "batch_insert", "calendar_id": calendar_id, "events": [
    {"task_id": ..., "title": ..., "start": ..., "end": ...},
    ...
]}
record request and response in history
```

**Transient error handling**: If the API returns `{"status": "error", ...}`, retry the same logical operation. Keep retrying until success. Record EVERY attempt (including failures) in history.jsonl.

### 5. Handle Emergencies

Process emergencies in chronological order by `arrival_time`.

For each emergency:

1. **Preserve completed work**: Keep events whose `end <= arrival_time`
2. **Delete interrupted/future events**: Delete every event whose `end > arrival_time`
   - Interrupted normal work gets NO partial credit; the task returns to the remaining pool at FULL duration
3. **Insert emergency**: At exactly `arrival_time`, ending at `arrival_time + duration_min`
   - Must finish by its deadline (if present) and by `work_end`
   - Status: "emergency"
4. **Rebuild remaining plan**: Starting at the emergency's end time, schedule remaining normal tasks using the same priority/dependency rules
   - Events created during replanning get status "rescheduled"
5. **Cascade misses**: If emergency cannot fit, or if remaining time is insufficient, mark tasks as missed

### 6. Write Output

**`/app/output.json`**:
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

Status values:
- `"scheduled"` - normal tasks in the initial plan
- `"rescheduled"` - normal tasks placed after an emergency replan
- `"emergency"` - emergency events

**`/app/history.jsonl`**: One JSON object per line:
```json
{"request": {...}, "response": {...}}
```
Record EVERY API call, including failed retries.

## Time Arithmetic Helper

Convert HH:MM to minutes from midnight for arithmetic:
```python
def to_minutes(time_str):
    h, m = map(int, time_str.split(":"))
    return h * 60 + m

def to_hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
```

## Implementation Pattern

The recommended implementation is a single Python script that:

1. Reads tasks.json
2. Reads simulator_intro.md (for contract reference)
3. Inspects api_simulator.py (for batch_insert detection)
4. Implements the scheduling algorithm
5. Communicates with the API via subprocess (piping stdin/stdout)
6. Handles all edge cases (dependencies, deadlines, emergencies, retries)
7. Writes output.json and history.jsonl

```python
import json, subprocess, sys, os

def run_api(commands, simulator_path="/app/api_simulator.py"):
    """Send commands to API simulator and collect responses."""
    input_text = "\n".join(json.dumps(c) for c in commands) + "\n"
    proc = subprocess.run(
        [sys.executable, simulator_path],
        input=input_text, capture_output=True, text=True
    )
    responses = []
    for line in proc.stdout.strip().split("\n"):
        if line.strip():
            responses.append(json.loads(line))
    return responses

def run_api_with_retry(commands, simulator_path="/app/api_simulator.py", history=None):
    """Send commands one at a time, retrying on transient errors."""
    results = []
    for cmd in commands:
        while True:
            proc = subprocess.run(
                [sys.executable, simulator_path],
                input=json.dumps(cmd) + "\n",
                capture_output=True, text=True
            )
            resp = json.loads(proc.stdout.strip())
            if history is not None:
                history.append({"request": cmd, "response": resp})
            if resp.get("status") == "ok":
                results.append(resp)
                break
            # Retry on error (transient)
    return results
```

**Important**: Each invocation of `api_simulator.py` is a separate process, but state persists via the state file (`/tmp/calendar_state.json`). So you can either:
- Send all commands in one invocation (pipe multiple lines to stdin)
- Send commands one at a time across multiple invocations

Both work because state is persisted. The single-invocation approach is simpler but if transient errors occur, you need to handle retries within that session.

## Edge Cases to Handle

1. **No tasks fit**: All tasks missed, empty schedule
2. **All tasks fit**: All scheduled, none missed
3. **Dependency cycles**: Tasks in a cycle can never have deps satisfied → mark as missed
4. **Duplicate titles**: Distinct task IDs remain distinct even with same title
5. **Task with deadline before work_start**: Cannot be scheduled → missed
6. **Emergency arrives at work_start**: All events deleted, emergency scheduled first
7. **Emergency with no deadline**: Just needs to fit within work_end
8. **Multiple emergencies**: Process sequentially, replanning between each
9. **batch_insert available**: Use it for initial plan submission when the simulator supports it
10. **Transient errors**: Retry the same command until success, recording all attempts

## Verification Checklist

After completing the task, verify:
- [ ] `/app/history.jsonl` exists with all API interactions recorded
- [ ] `/app/output.json` exists with correct format
- [ ] Schedule events are chronological and non-overlapping
- [ ] First API call was `clear`
- [ ] Final simulator state matches output.json (verify with `list` command)
- [ ] All emergencies were handled in chronological order
- [ ] Dependency constraints are respected
- [ ] Deadline constraints are respected
- [ ] Status labels are correct (scheduled/rescheduled/emergency)

## Complete Reference Implementation

```python
#!/usr/bin/env python3
"""API Scheduler - complete reference implementation."""
import json, subprocess, sys, os

# ── Time helpers (defined first — used everywhere below) ─────────────────
def to_minutes(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m

def to_hhmm(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"

# ── Load inputs ──────────────────────────────────────────────────────────
with open("/app/tasks.json") as f:
    data = json.load(f)

tasks = data["tasks"]
emergencies = data.get("emergencies", [])
config = data["config"]
calendar_id = config["calendar_id"]
work_start_min = to_minutes(config["work_start"])
work_end_min = to_minutes(config["work_end"])
priority_method = config["priority_method"]

# ── Detect batch_insert support ──────────────────────────────────────────
with open("/app/api_simulator.py") as f:
    sim_source = f.read()
has_batch = "batch_insert" in sim_source

# ── Priority scoring ─────────────────────────────────────────────────────
def compute_score(task):
    u, i = task["urgency"], task["importance"]
    t = task.get("team_priority")
    if priority_method == "urgency":
        return u
    elif priority_method == "eisenhower":
        return u * i
    elif priority_method == "weighted":
        return (0.5*u + 0.3*i + 0.2*t) if t is not None else (0.6*u + 0.4*i)

def priority_key(task):
    score = compute_score(task)
    dl = to_minutes(task["deadline"]) if task.get("deadline") else float("inf")
    return (-score, dl, tasks.index(task))

# ── API interaction ──────────────────────────────────────────────────────
history = []

def api_call(cmd):
    proc = subprocess.run(
        [sys.executable, "/app/api_simulator.py"],
        input=json.dumps(cmd) + "\n",
        capture_output=True, text=True
    )
    resp = json.loads(proc.stdout.strip())
    history.append({"request": cmd, "response": resp})
    return resp

def api_call_with_retry(cmd, max_retries=20):
    for _ in range(max_retries):
        resp = api_call(cmd)
        if resp.get("status") == "ok":
            return resp
    raise RuntimeError(f"Failed after {max_retries} retries: {cmd}")

# ── Scheduling algorithm ─────────────────────────────────────────────────
def build_schedule(remaining_tasks, current_time, completed_ids, status_label):
    """Greedy dependency-aware scheduler. Returns (events, completed, missed, final_time)."""
    events = []
    remaining = list(remaining_tasks)
    completed = set(completed_ids)
    missed = set()

    while remaining:
        # Remove any tasks whose deps are now known to be missed
        changed = True
        while changed:
            changed = False
            for t in list(remaining):
                if any(d in missed for d in t.get("depends_on", [])):
                    remaining.remove(t)
                    missed.add(t["id"])
                    changed = True

        if not remaining:
            break

        # Find eligible: all deps in completed set
        eligible = [t for t in remaining
                    if all(d in completed for d in t.get("depends_on", []))]
        if not eligible:
            # Deadlock / unresolvable deps (cycle)
            for t in remaining:
                missed.add(t["id"])
            break

        eligible.sort(key=priority_key)
        task = eligible[0]
        remaining.remove(task)
        end_time = current_time + task["duration_min"]
        deadline = task.get("deadline")
        deadline_ok = (deadline is None) or (end_time <= to_minutes(deadline))
        work_ok = end_time <= work_end_min

        if deadline_ok and work_ok:
            events.append({
                "task_id": task["id"],
                "title": task["title"],
                "start": to_hhmm(current_time),
                "end": to_hhmm(end_time),
                "status": status_label
            })
            completed.add(task["id"])
            current_time = end_time
        else:
            missed.add(task["id"])
            # current_time does NOT advance for missed tasks

    return events, completed, missed, current_time

def cascade_miss(missed_id, remaining, missed_ids):
    """Remove all tasks that transitively depend on missed_id.
    Checks against the full missed_ids set so chains A->B->C cascade correctly."""
    missed_ids.add(missed_id)
    changed = True
    while changed:
        changed = False
        to_remove = [t for t in remaining
                     if any(d in missed_ids for d in t.get("depends_on", []))]
        for t in to_remove:
            remaining.remove(t)
            missed_ids.add(t["id"])
            changed = True

# ── Main flow ────────────────────────────────────────────────────────────
# 1. Initial schedule
initial_events, completed_ids, missed_ids, current_time = \
    build_schedule(tasks, work_start_min, set(), "scheduled")

# 2. Submit to API
api_call_with_retry({"cmd": "clear", "calendar_id": calendar_id})

if has_batch and initial_events:
    batch_events = [{"task_id": e["task_id"], "title": e["title"],
                     "start": e["start"], "end": e["end"]} for e in initial_events]
    api_call_with_retry({"cmd": "batch_insert", "calendar_id": calendar_id, "events": batch_events})
else:
    for evt in initial_events:
        api_call_with_retry({
            "cmd": "insert", "calendar_id": calendar_id,
            "event": {"task_id": evt["task_id"], "title": evt["title"],
                      "start": evt["start"], "end": evt["end"]}
        })

# 3. Handle emergencies
all_events = list(initial_events)

for emerg in sorted(emergencies, key=lambda e: to_minutes(e["arrival_time"])):
    arrival = to_minutes(emerg["arrival_time"])

    # Preserve events ending at or before arrival
    preserved = [e for e in all_events if to_minutes(e["end"]) <= arrival]
    # Delete events ending after arrival
    to_delete = [e for e in all_events if to_minutes(e["end"]) > arrival]

    # Delete via API
    # First list to get event IDs
    list_resp = api_call_with_retry({"cmd": "list", "calendar_id": calendar_id})
    api_events = list_resp.get("events", [])
    for ae in api_events:
        if to_minutes(ae["end"]) > arrival:
            api_call_with_retry({"cmd": "delete", "calendar_id": calendar_id, "event_id": ae["id"]})

    # Insert emergency
    emerg_end = arrival + emerg["duration_min"]
    emerg_event = {
        "task_id": emerg["id"], "title": emerg["title"],
        "start": to_hhmm(arrival), "end": to_hhmm(emerg_end),
        "status": "emergency"
    }
    api_call_with_retry({
        "cmd": "insert", "calendar_id": calendar_id,
        "event": {"task_id": emerg_event["task_id"], "title": emerg_event["title"],
                  "start": emerg_event["start"], "end": emerg_event["end"]}
    })

    # Rebuild remaining plan
    preserved_ids = set(e["task_id"] for e in preserved)
    deleted_ids = set(e["task_id"] for e in to_delete)
    # Remaining = tasks not yet completed (preserved) and not yet missed
    remaining_tasks = [t for t in tasks
                       if t["id"] not in preserved_ids
                       and t["id"] not in missed_ids]

    new_events, new_completed, new_missed, current_time = \
        build_schedule(remaining_tasks, emerg_end, preserved_ids, "rescheduled")

    # Submit new events to API
    for evt in new_events:
        api_call_with_retry({
            "cmd": "insert", "calendar_id": calendar_id,
            "event": {"task_id": evt["task_id"], "title": evt["title"],
                      "start": evt["start"], "end": evt["end"]}
        })

    missed_ids.update(new_missed)
    all_events = preserved + [emerg_event] + new_events

# 4. Write outputs
all_events.sort(key=lambda e: to_minutes(e["start"]))

# completed/missed refer to normal tasks only (not emergencies)
normal_task_ids = set(t["id"] for t in tasks)
scheduled_normal_ids = set(e["task_id"] for e in all_events
                           if e["status"] in ("scheduled", "rescheduled"))
completed_list = sorted(scheduled_normal_ids & normal_task_ids)
missed_list = sorted(missed_ids & normal_task_ids)

output = {
    "schedule": all_events,
    "completion_summary": {
        "completed": completed_list,
        "missed": missed_list,
        "total_tasks": len(tasks),
        "completed_count": len(completed_list),
        "missed_count": len(missed_list)
    }
}

with open("/app/output.json", "w") as f:
    json.dump(output, f, indent=2)

with open("/app/history.jsonl", "w") as f:
    for h in history:
        f.write(json.dumps(h) + "\n")
```
