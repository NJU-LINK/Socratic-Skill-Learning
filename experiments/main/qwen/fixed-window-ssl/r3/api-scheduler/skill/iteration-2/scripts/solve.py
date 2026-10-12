#!/usr/bin/env python3
"""
General API Scheduler - handles the full api-scheduler family.
Reads tasks.json, interacts with api_simulator.py, produces output.json and history.jsonl.

Key invariants:
- Schedule events have NO status field (must match simulator state exactly)
- completed and missed lists are sorted alphabetically
- Schedule is sorted by (start, task_id)
- First mutating API call is always clear
- All API requests/responses recorded in history.jsonl
"""
import json
import subprocess
import sys
import os
import time

# ─── Load task data ───────────────────────────────────────────────────────────
with open("/app/tasks.json") as f:
    task_data = json.load(f)

tasks = task_data["tasks"]
emergencies = task_data.get("emergencies", [])
config = task_data["config"]

CALENDAR_ID = config["calendar_id"]
WORK_START = config["work_start"]
WORK_END = config["work_end"]
PRIORITY_METHOD = config["priority_method"]

HISTORY = []
SIM_PATH = "/app/api_simulator.py"

# ─── Time helpers ─────────────────────────────────────────────────────────────
def time_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"

WORK_START_MIN = time_to_min(WORK_START)
WORK_END_MIN = time_to_min(WORK_END)

# ─── Priority scoring ────────────────────────────────────────────────────────
def compute_score(task):
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", None)
    if PRIORITY_METHOD == "urgency":
        return u
    elif PRIORITY_METHOD == "eisenhower":
        return u * i
    elif PRIORITY_METHOD == "weighted":
        if t is not None:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
    else:
        raise ValueError(f"Unknown priority method: {PRIORITY_METHOD}")

def sort_key(task):
    """Higher score first; tie-break: earlier deadline, no-deadline after, then input order."""
    score = compute_score(task)
    deadline = task.get("hard_deadline", None)
    if deadline is not None:
        deadline_val = time_to_min(deadline)
        has_deadline = 0
    else:
        deadline_val = float('inf')
        has_deadline = 1
    idx = task["_index"]
    return (-score, has_deadline, deadline_val, idx)

# ─── API interaction ──────────────────────────────────────────────────────────
def call_sim(cmd_dict, max_retries=10):
    """Send command to simulator, retry on transient errors."""
    for attempt in range(max_retries):
        req_json = json.dumps(cmd_dict)
        result = subprocess.run(
            ["python3", SIM_PATH],
            input=req_json + "\n",
            capture_output=True, text=True, timeout=30
        )
        resp_text = result.stdout.strip()
        if not resp_text:
            time.sleep(0.1)
            continue
        try:
            resp = json.loads(resp_text)
        except json.JSONDecodeError:
            time.sleep(0.1)
            continue
        HISTORY.append({"request": cmd_dict, "response": resp})
        if resp.get("status") == "ok":
            return resp
        msg = resp.get("message", "")
        if "Rate limit" in msg or "Internal server error" in msg:
            time.sleep(0.1)
            continue
        else:
            return resp
    return {"status": "error", "message": "Max retries exceeded"}

def has_batch_insert():
    """Detect if the simulator supports batch_insert by inspecting its source."""
    with open(SIM_PATH) as f:
        return "batch_insert" in f.read()

# ─── Scheduling algorithm ────────────────────────────────────────────────────
def build_schedule(task_list, cursor_min, completed_ids, task_map):
    """
    Greedy: repeatedly pick highest-priority task with deps met.
    Schedule at cursor if it fits within deadline and work_end; else mark missed.
    If a prerequisite is missed, cascade miss to dependents.
    """
    events = []
    remaining = list(task_list)
    missed = set()

    while remaining:
        remaining.sort(key=lambda t: sort_key(t))
        placed = False
        for task in remaining:
            tid = task["id"]
            deps = task.get("depends_on", [])
            deps_missed = any(d in missed for d in deps)
            deps_met = all(d in completed_ids for d in deps)

            if deps_missed:
                missed.add(tid)
                remaining.remove(task)
                placed = True
                break
            if not deps_met:
                continue

            duration = task["duration_min"]
            end_min = cursor_min + duration

            hard_deadline = task.get("hard_deadline", None)
            if hard_deadline is not None and end_min > time_to_min(hard_deadline):
                missed.add(tid)
                remaining.remove(task)
                placed = True
                break
            if end_min > WORK_END_MIN:
                missed.add(tid)
                remaining.remove(task)
                placed = True
                break

            events.append({
                "task_id": tid,
                "title": task["title"],
                "start": min_to_time(cursor_min),
                "end": min_to_time(end_min),
            })
            completed_ids.add(tid)
            cursor_min = end_min
            remaining.remove(task)
            placed = True
            break

        if not placed:
            for task in remaining:
                missed.add(task["id"])
            break

    return events, completed_ids, missed, cursor_min

# ─── Main ─────────────────────────────────────────────────────────────────────
for i, t in enumerate(tasks):
    t["_index"] = i
task_map = {t["id"]: t for t in tasks}

# 1. Clear calendar
resp = call_sim({"cmd": "clear", "calendar_id": CALENDAR_ID})
assert resp["status"] == "ok", f"Clear failed: {resp}"

# 2. Build initial schedule
completed_ids = set()
initial_events, completed_ids, missed_ids, cursor_min = build_schedule(
    tasks, WORK_START_MIN, completed_ids, task_map
)

# 3. Submit initial plan
use_batch = has_batch_insert()
if use_batch and initial_events:
    batch_evts = [{"task_id": e["task_id"], "title": e["title"],
                   "start": e["start"], "end": e["end"]} for e in initial_events]
    call_sim({"cmd": "batch_insert", "calendar_id": CALENDAR_ID, "events": batch_evts})
else:
    for evt in initial_events:
        call_sim({"cmd": "insert", "calendar_id": CALENDAR_ID,
                  "event": {"task_id": evt["task_id"], "title": evt["title"],
                            "start": evt["start"], "end": evt["end"]}})

# Track events with internal status (for completed/missed determination)
all_events = [{**e, "_status": "scheduled"} for e in initial_events]

# 4. Handle emergencies
if emergencies:
    for emerg in sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"])):
        arrival_min = time_to_min(emerg["arrival_time"])
        emerg_end_min = arrival_min + emerg["duration_min"]

        preserved = []
        to_delete = []
        for evt in all_events:
            if evt["_status"] in ("scheduled", "rescheduled"):
                if time_to_min(evt["end"]) <= arrival_min:
                    preserved.append(evt)
                else:
                    to_delete.append(evt)
            else:
                preserved.append(evt)

        list_resp = call_sim({"cmd": "list", "calendar_id": CALENDAR_ID})
        sim_by_task = {se["task_id"]: se for se in list_resp.get("events", [])}
        for evt in to_delete:
            if evt["task_id"] in sim_by_task:
                eid = sim_by_task[evt["task_id"]]["id"]
                call_sim({"cmd": "delete", "calendar_id": CALENDAR_ID, "event_id": eid})

        emerg_tid = emerg.get("id", emerg.get("task_id", "EMERGENCY"))
        emerg_event = {
            "task_id": emerg_tid, "title": emerg["title"],
            "start": emerg["arrival_time"], "end": min_to_time(emerg_end_min),
            "_status": "emergency"
        }
        call_sim({"cmd": "insert", "calendar_id": CALENDAR_ID,
                  "event": {"task_id": emerg_tid, "title": emerg["title"],
                            "start": emerg["arrival_time"], "end": emerg_event["end"]}})

        deleted_tids = {e["task_id"] for e in to_delete if e["_status"] in ("scheduled", "rescheduled")}
        rebuild_tasks = [task_map[tid] for tid in deleted_tids if tid in task_map]
        for tid in list(missed_ids):
            if tid in task_map:
                rebuild_tasks.append(task_map[tid])

        completed_ids = {e["task_id"] for e in preserved if e["_status"] in ("scheduled", "rescheduled")}
        new_events, completed_ids, new_missed, cursor_min = build_schedule(
            rebuild_tasks, emerg_end_min, completed_ids, task_map
        )

        for evt in new_events:
            evt["_status"] = "rescheduled"
            call_sim({"cmd": "insert", "calendar_id": CALENDAR_ID,
                      "event": {"task_id": evt["task_id"], "title": evt["title"],
                                "start": evt["start"], "end": evt["end"]}})

        all_events = preserved + [emerg_event] + new_events
        missed_ids = new_missed
        for evt in new_events:
            missed_ids.discard(evt["task_id"])

# 5. Build all_task_ids (normal + emergencies)
all_task_ids = {t["id"] for t in tasks}
for e in emergencies:
    all_task_ids.add(e.get("id", e.get("task_id", "EMERGENCY")))

# 6. Final verification
call_sim({"cmd": "list", "calendar_id": CALENDAR_ID})

# 7. Write output
# Schedule: events WITHOUT status (to match simulator state exactly)
# Sorted by (start, task_id) to match test expectations
normal_and_emergency_events = [
    e for e in all_events if e["_status"] in ("scheduled", "rescheduled", "emergency")
]
output_events = sorted(
    [{"task_id": e["task_id"], "title": e["title"],
      "start": e["start"], "end": e["end"]}
     for e in normal_and_emergency_events],
    key=lambda e: (e["start"], e["task_id"])
)

# Completion summary:
# - completed = sorted task_ids from schedule (includes emergencies)
# - missed = complement of completed against all_task_ids
# - total_tasks = len(all_task_ids)
completed_list = sorted(e["task_id"] for e in output_events)
missed_list = sorted(all_task_ids - set(completed_list))

output = {
    "schedule": output_events,
    "completion_summary": {
        "completed": completed_list,
        "missed": missed_list,
        "total_tasks": len(all_task_ids),
        "completed_count": len(completed_list),
        "missed_count": len(missed_list)
    }
}

with open("/app/output.json", "w") as f:
    json.dump(output, f, indent=2)
with open("/app/history.jsonl", "w") as f:
    for entry in HISTORY:
        f.write(json.dumps(entry) + "\n")

print("=== Schedule ===")
for evt in output_events:
    print(f"  {evt['task_id']}: {evt['start']}-{evt['end']}")
print(f"Completed: {completed_list}")
print(f"Missed: {missed_list}")
print(f"History: {len(HISTORY)} entries")
