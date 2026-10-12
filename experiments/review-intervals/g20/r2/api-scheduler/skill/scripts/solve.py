#!/usr/bin/env python3
"""
General-purpose API scheduler solver - iteration 3.
Correct output format: schedule entries MUST include status field.
Status values: "scheduled" (initial plan), "rescheduled" (after emergency), "emergency" (emergency events).
completed/missed lists must be sorted alphabetically.
"""
import json, subprocess, sys, os

# ─── Load task data ───────────────────────────────────────────────────────────
with open("/app/tasks.json") as f:
    data = json.load(f)

tasks = data["tasks"]
emergencies = data.get("emergencies", [])
config = data["config"]

work_start = config["work_start"]
work_end = config["work_end"]
priority_method = config["priority_method"]
calendar_id = config["calendar_id"]

# ─── Time helpers ─────────────────────────────────────────────────────────────
def time_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"

work_start_min = time_to_min(work_start)
work_end_min = time_to_min(work_end)

# ─── Priority scoring ─────────────────────────────────────────────────────────
def compute_score(task, method):
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", None)
    if method == "urgency":
        return u
    elif method == "eisenhower":
        return u * i
    elif method == "weighted":
        if t is not None:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
    else:
        raise ValueError(f"Unknown priority method: {method}")

# ─── Sort tasks by priority ───────────────────────────────────────────────────
task_index = {t["id"]: idx for idx, t in enumerate(tasks)}

def sort_key(task):
    score = compute_score(task, priority_method)
    deadline = task.get("deadline", None)
    if deadline is not None:
        dl_min = time_to_min(deadline)
        deadline_key = (0, dl_min)
    else:
        deadline_key = (1, 0)
    orig_idx = task_index[task["id"]]
    return (-score, deadline_key, orig_idx)

sorted_tasks = sorted(tasks, key=sort_key)

# ─── Build schedule (greedy, dependency-aware) ────────────────────────────────
def build_schedule(task_list, start_min, end_min, depends_on_map, already_completed, status_label="scheduled"):
    """
    Greedily schedule tasks by priority order, respecting dependencies.
    Returns (scheduled_events, missed_ids).
    Each event includes status field.
    """
    scheduled = []
    missed = []
    completed_ids = set(already_completed)
    remaining = list(task_list)
    cursor = start_min
    
    while remaining:
        chosen = None
        chosen_idx = None
        for idx, t in enumerate(remaining):
            deps = depends_on_map.get(t["id"], [])
            if all(d in completed_ids for d in deps):
                chosen = t
                chosen_idx = idx
                break
        
        if chosen is None:
            for t in remaining:
                missed.append(t["id"])
            break
        
        end_time = cursor + chosen["duration_min"]
        deadline = chosen.get("deadline", None)
        
        fits = end_time <= end_min
        if deadline is not None:
            fits = fits and end_time <= time_to_min(deadline)
        
        if fits:
            scheduled.append({
                "task_id": chosen["id"],
                "title": chosen["title"],
                "start": min_to_time(cursor),
                "end": min_to_time(end_time),
                "status": status_label
            })
            completed_ids.add(chosen["id"])
            cursor = end_time
            remaining.pop(chosen_idx)
        else:
            missed.append(chosen["id"])
            remaining.pop(chosen_idx)
            changed = True
            while changed:
                changed = False
                new_remaining = []
                for t in remaining:
                    deps = depends_on_map.get(t["id"], [])
                    if chosen["id"] in deps:
                        missed.append(t["id"])
                        changed = True
                    else:
                        new_remaining.append(t)
                remaining = new_remaining
    
    return scheduled, missed

depends_on_map = {}
for t in tasks:
    deps = t.get("depends_on", [])
    if deps:
        depends_on_map[t["id"]] = deps

# ─── API interaction ──────────────────────────────────────────────────────────
history = []
event_map = {}

def api_call_raw(cmd_dict):
    req = json.dumps(cmd_dict)
    result = subprocess.run(
        ["python3", "/app/api_simulator.py"],
        input=req + "\n",
        capture_output=True, text=True
    )
    resp_line = result.stdout.strip()
    if not resp_line:
        return {"status": "error", "message": "No response from simulator"}
    return json.loads(resp_line)

def api_call(cmd_dict):
    max_attempts = 10
    for attempt in range(max_attempts):
        resp = api_call_raw(cmd_dict)
        history.append({"request": cmd_dict, "response": resp})
        
        if resp.get("status") == "ok":
            return resp
        
        msg = resp.get("message", "")
        is_transient = ("Rate limit" in msg or "Internal server" in msg or "Try again" in msg)
        
        if is_transient:
            continue
        else:
            return resp
    
    return resp

def api_insert_event(task_id, title, start, end):
    resp = api_call({
        "cmd": "insert",
        "calendar_id": calendar_id,
        "event": {
            "task_id": task_id,
            "title": title,
            "start": start,
            "end": end
        }
    })
    if resp.get("status") == "ok":
        event_map[task_id] = resp["event_id"]
    return resp

def api_delete_event(event_id):
    return api_call({
        "cmd": "delete",
        "calendar_id": calendar_id,
        "event_id": event_id
    })

# ─── Build and submit initial schedule ────────────────────────────────────────
print("Priority order:", [t["id"] for t in sorted_tasks])

initial_events, initial_missed = build_schedule(
    sorted_tasks, work_start_min, work_end_min, depends_on_map, set(), status_label="scheduled"
)

print("\nInitial schedule:")
for evt in initial_events:
    print(f"  {evt['task_id']}: {evt['start']}-{evt['end']} ({evt['status']})")
print(f"Missed: {initial_missed}")

print("\n--- API Interaction ---")
resp = api_call({"cmd": "clear", "calendar_id": calendar_id})
print(f"Clear: {resp}")

for evt in initial_events:
    resp = api_insert_event(evt["task_id"], evt["title"], evt["start"], evt["end"])
    print(f"Insert {evt['task_id']}: {resp}")

resp = api_call({"cmd": "list", "calendar_id": calendar_id})
print(f"List: {resp}")

# ─── Handle emergencies ──────────────────────────────────────────────────────
all_normal_task_ids = set(t["id"] for t in tasks)
all_missed = set(initial_missed)

if emergencies:
    print("\n--- Handling Emergencies ---")
    emergencies_sorted = sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"]))
    full_schedule = list(initial_events)
    
    for emerg in emergencies_sorted:
        arrival_min = time_to_min(emerg["arrival_time"])
        emerg_id = emerg.get("id") or emerg.get("task_id")
        print(f"\nEmergency '{emerg_id}' at {emerg['arrival_time']}")
        
        list_resp = api_call({"cmd": "list", "calendar_id": calendar_id})
        current_events = list_resp.get("events", [])
        
        preserved = []
        to_delete = []
        for evt in current_events:
            evt_end_min = time_to_min(evt["end"])
            if evt_end_min <= arrival_min:
                preserved.append(evt)
            else:
                to_delete.append(evt)
        
        deleted_task_ids = set()
        for evt in to_delete:
            eid = evt["id"]
            tid = evt.get("task_id", "")
            deleted_task_ids.add(tid)
            resp = api_delete_event(eid)
            print(f"  Delete {tid} ({eid}): {resp}")
            if tid in event_map:
                del event_map[tid]
        
        full_schedule = [e for e in full_schedule if e["task_id"] not in deleted_task_ids]
        
        emerg_end_min = arrival_min + emerg["duration_min"]
        emerg_event = {
            "task_id": emerg_id,
            "title": emerg["title"],
            "start": emerg["arrival_time"],
            "end": min_to_time(emerg_end_min),
            "status": "emergency"
        }
        resp = api_insert_event(emerg_id, emerg["title"], emerg["arrival_time"], emerg_event["end"])
        print(f"  Insert emergency {emerg_id}: {resp}")
        full_schedule.append(emerg_event)
        
        completed_normal = set()
        for evt in preserved:
            tid = evt.get("task_id", "")
            if tid in all_normal_task_ids:
                completed_normal.add(tid)
        
        remaining_normal = [
            t for t in sorted_tasks 
            if t["id"] not in completed_normal and t["id"] not in all_missed
        ]
        
        rebuilt_events, rebuilt_missed = build_schedule(
            remaining_normal, emerg_end_min, work_end_min, depends_on_map, completed_normal, status_label="rescheduled"
        )
        
        for evt in rebuilt_events:
            resp = api_insert_event(evt["task_id"], evt["title"], evt["start"], evt["end"])
            print(f"  Reschedule {evt['task_id']}: {resp}")
        
        full_schedule.extend(rebuilt_events)
        all_missed.update(rebuilt_missed)
        full_schedule.sort(key=lambda e: time_to_min(e["start"]))
    
    final_schedule = full_schedule
else:
    final_schedule = initial_events

# ─── Compute completion summary ───────────────────────────────────────────────
all_scheduled_ids = sorted([evt["task_id"] for evt in final_schedule])
missed_ids = sorted([tid for tid in [t["id"] for t in tasks] if tid not in all_scheduled_ids])

output = {
    "schedule": final_schedule,
    "completion_summary": {
        "completed": all_scheduled_ids,
        "missed": missed_ids,
        "total_tasks": len(tasks),
        "completed_count": len(all_scheduled_ids),
        "missed_count": len(missed_ids)
    }
}

with open("/app/output.json", "w") as f:
    json.dump(output, f, indent=2)

with open("/app/history.jsonl", "w") as f:
    for entry in history:
        f.write(json.dumps(entry) + "\n")

print("\n--- Final Output ---")
print(json.dumps(output, indent=2))
print(f"\nHistory entries: {len(history)}")
print(f"Event map: {event_map}")
print("Done!")
