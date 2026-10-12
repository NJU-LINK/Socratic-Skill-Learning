#!/usr/bin/env python3
"""
Reference implementation for the api-scheduler skill family.
Adapts to any valid in-family task by reading tasks.json and the simulator.

Usage: python3 scheduler.py
Assumes: /app/tasks.json, /app/api_simulator.py, /app/simulator_intro.md exist
Produces: /app/output.json, /app/history.jsonl
"""
import json
import subprocess
import sys
import os

# ─── Load task data ──────────────────────────────────────────────────────────
with open("/app/tasks.json") as f:
    task_data = json.load(f)

tasks = task_data["tasks"]
emergencies = task_data.get("emergencies", [])
config = task_data["config"]
calendar_id = config["calendar_id"]
work_start = config["work_start"]
work_end = config["work_end"]
priority_method = config["priority_method"]

# ─── Time utilities ──────────────────────────────────────────────────────────
def time_to_min(t):
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m):
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{m // 60:02d}:{m % 60:02d}"

work_start_min = time_to_min(work_start)
work_end_min = time_to_min(work_end)

# ─── Priority scoring ────────────────────────────────────────────────────────
def compute_score(task, method):
    """Compute priority score based on the configured method."""
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

def sort_key(task, method, original_index):
    """
    Sort key for priority ordering.
    Higher score first. Tie-break: earlier deadline first; no deadline sorts
    after one with deadline. Further tie-break: original order in tasks.json.
    """
    score = compute_score(task, method)
    deadline = task.get("deadline", None)
    if deadline is not None:
        deadline_min = time_to_min(deadline)
        has_deadline = 0  # sorts before 1
    else:
        deadline_min = float('inf')
        has_deadline = 1
    return (-score, has_deadline, deadline_min, original_index)

# ─── Detect batch_insert capability ─────────────────────────────────────────
def has_batch_insert():
    """Check if the simulator supports batch_insert."""
    try:
        with open("/app/api_simulator.py") as f:
            return "batch_insert" in f.read()
    except FileNotFoundError:
        return False

# ─── API interaction with retry ──────────────────────────────────────────────
history = []

def api_call(cmd_dict, max_retries=5):
    """
    Send a command to the simulator with retry logic.
    Records EVERY attempt (including failures) in history.
    """
    for attempt in range(max_retries):
        req_json = json.dumps(cmd_dict)
        proc = subprocess.run(
            ["python3", "/app/api_simulator.py"],
            input=req_json + "\n",
            capture_output=True, text=True, timeout=30
        )
        resp_text = proc.stdout.strip()
        if not resp_text:
            resp = {"status": "error", "message": "Empty response"}
        else:
            resp = json.loads(resp_text)
        
        # Log every attempt
        history.append({"request": cmd_dict, "response": resp})
        
        if resp.get("status") == "ok":
            return resp
        
        # Retry on transient errors
        msg = resp.get("message", "")
        if "Rate limit" in msg or "Internal server error" in msg or "Try again" in msg:
            continue
        
        # Non-retryable error - return immediately
        return resp
    
    # All retries exhausted
    return history[-1]["response"]

# ─── Task management ────────────────────────────────────────────────────────
task_map = {t["id"]: t for t in tasks}
task_indices = {t["id"]: i for i, t in enumerate(tasks)}

def cascade_missed(missed_id, remaining, missed_list):
    """Mark all tasks transitively depending on missed_id as missed.
    
    Uses BFS through the dependency DAG: track all newly-missed tasks per
    iteration and cascade from each, not just the last one. This handles
    fan-out patterns (e.g., A→B, A→C, B→D, C→E) correctly.
    """
    newly_missed = [missed_id]
    while newly_missed:
        next_batch = []
        for mid in newly_missed:
            for tid in list(remaining):
                t = task_map[tid]
                if mid in t.get("depends_on", []):
                    remaining.remove(tid)
                    missed_list.append(tid)
                    next_batch.append(tid)
        newly_missed = next_batch

def build_schedule(remaining_task_ids, cursor_min, status_label="scheduled", pre_completed=None):
    """
    Greedily schedule tasks by priority, respecting dependencies and deadlines.
    pre_completed: set of task IDs already completed before this rebuild (e.g., preserved after emergency)
    Returns (events, completed_ids, missed_ids, final_cursor).
    """
    events = []
    completed = []
    missed = []
    scheduled_set = set(pre_completed) if pre_completed else set()
    remaining = set(remaining_task_ids)
    cursor = cursor_min
    
    while remaining:
        # Find tasks whose dependencies are all satisfied
        schedulable = []
        for tid in remaining:
            t = task_map[tid]
            deps = t.get("depends_on", [])
            if all(d in scheduled_set or d in completed for d in deps):
                schedulable.append(tid)
        
        if not schedulable:
            # Dependency deadlock - all remaining are missed
            for tid in sorted(remaining, key=lambda x: task_indices.get(x, 999)):
                missed.append(tid)
            break
        
        # Sort by priority (highest first)
        schedulable.sort(key=lambda tid: sort_key(
            task_map[tid], priority_method, task_indices[tid]
        ))
        
        chosen_id = schedulable[0]
        chosen = task_map[chosen_id]
        duration = chosen["duration_min"]
        deadline = chosen.get("deadline", None)
        
        start_min = cursor
        end_min = start_min + duration
        
        # Check work_end constraint
        if end_min > work_end_min:
            missed.append(chosen_id)
            remaining.remove(chosen_id)
            cascade_missed(chosen_id, remaining, missed)
            continue
        
        # Check hard deadline constraint
        if deadline is not None and end_min > time_to_min(deadline):
            missed.append(chosen_id)
            remaining.remove(chosen_id)
            cascade_missed(chosen_id, remaining, missed)
            continue
        
        # Schedule this task
        events.append({
            "task_id": chosen_id,
            "title": chosen["title"],
            "start": min_to_time(start_min),
            "end": min_to_time(end_min),
            "status": status_label
        })
        completed.append(chosen_id)
        scheduled_set.add(chosen_id)
        remaining.remove(chosen_id)
        cursor = end_min
    
    return events, completed, missed, cursor

# ═══ MAIN EXECUTION ═════════────────────────────────────────────────────────

# Step 1: Clear the calendar (mandatory first call)
api_call({"cmd": "clear", "calendar_id": calendar_id})

# Step 2: Build initial schedule
all_task_ids = [t["id"] for t in tasks]
initial_events, initial_completed, initial_missed, cursor = build_schedule(
    all_task_ids, work_start_min, "scheduled"
)

# Step 3: Submit initial plan to API
event_id_map = {}  # task_id → event_id (for later deletion)

if has_batch_insert() and initial_events:
    # Use batch insert if available
    batch_events = [
        {"task_id": e["task_id"], "title": e["title"],
         "start": e["start"], "end": e["end"]}
        for e in initial_events
    ]
    resp = api_call({
        "cmd": "batch_insert",
        "calendar_id": calendar_id,
        "events": batch_events
    })
    if resp.get("status") == "ok":
        # Map task_ids to event_ids from batch response
        for i, evt in enumerate(initial_events):
            if "event_ids" in resp and i < len(resp["event_ids"]):
                event_id_map[evt["task_id"]] = resp["event_ids"][i]
else:
    # Individual inserts
    for evt in initial_events:
        resp = api_call({
            "cmd": "insert",
            "calendar_id": calendar_id,
            "event": {
                "task_id": evt["task_id"],
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"]
            }
        })
        if resp.get("status") == "ok":
            event_id_map[evt["task_id"]] = resp["event_id"]

# Step 4: Handle emergencies chronologically
emergencies_sorted = sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"]))

current_events = list(initial_events)
all_completed = list(initial_completed)
all_missed = list(initial_missed)

for emerg in emergencies_sorted:
    arrival_min = time_to_min(emerg["arrival_time"])
    
    # Step 4a: Preserve events ending at or before arrival
    preserved = []
    to_delete = []
    for evt in current_events:
        evt_end_min = time_to_min(evt["end"])
        if evt_end_min <= arrival_min:
            preserved.append(evt)
        else:
            to_delete.append(evt)
    
    # Step 4b: Delete interrupted/future events
    for evt in to_delete:
        tid = evt["task_id"]
        if tid in event_id_map:
            api_call({
                "cmd": "delete",
                "calendar_id": calendar_id,
                "event_id": event_id_map[tid]
            })
        # Return normal tasks to the remaining pool (full duration, no partial credit)
        if evt.get("status") in ("scheduled", "rescheduled"):
            if tid in all_completed:
                all_completed.remove(tid)
    
    current_events = preserved
    
    # Step 4c: Insert the emergency at its arrival time
    emerg_duration = emerg["duration_min"]
    emerg_start = arrival_min
    emerg_end = emerg_start + emerg_duration
    
    emerg_event = {
        "task_id": emerg["id"],
        "title": emerg["title"],
        "start": min_to_time(emerg_start),
        "end": min_to_time(emerg_end),
        "status": "emergency"
    }
    
    resp = api_call({
        "cmd": "insert",
        "calendar_id": calendar_id,
        "event": {
            "task_id": emerg["id"],
            "title": emerg["title"],
            "start": emerg_event["start"],
            "end": emerg_event["end"]
        }
    })
    if resp.get("status") == "ok":
        event_id_map[emerg["id"]] = resp["event_id"]
    
    current_events.append(emerg_event)
    
    # Step 4d: Rebuild remaining normal plan from emergency's end
    completed_so_far = set(e["task_id"] for e in preserved)
    remaining_normal = [tid for tid in all_task_ids if tid not in completed_so_far]
    
    new_events, new_completed, new_missed, cursor = build_schedule(
        remaining_normal, emerg_end, "rescheduled", pre_completed=completed_so_far
    )
    
    # Submit new events to API
    for evt in new_events:
        resp = api_call({
            "cmd": "insert",
            "calendar_id": calendar_id,
            "event": {
                "task_id": evt["task_id"],
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"]
            }
        })
        if resp.get("status") == "ok":
            event_id_map[evt["task_id"]] = resp["event_id"]
    
    current_events.extend(new_events)
    all_completed.extend(new_completed)
    all_missed.extend(new_missed)

# Step 5: Verify final state with list call
api_call({"cmd": "list", "calendar_id": calendar_id})

# Step 6: Write outputs
final_schedule = sorted(current_events, key=lambda e: time_to_min(e["start"]))

# Compute completion summary
all_normal_ids = set(t["id"] for t in tasks)
completed_set = set(all_completed)
missed_set = set(all_missed)
for tid in all_normal_ids:
    if tid not in completed_set and tid not in missed_set:
        missed_set.add(tid)

output = {
    "schedule": final_schedule,
    "completion_summary": {
        "completed": sorted(all_completed),
        "missed": sorted(missed_set),
        "total_tasks": len(tasks),
        "completed_count": len(all_completed),
        "missed_count": len(missed_set)
    }
}

with open("/app/output.json", "w") as f:
    json.dump(output, f, indent=2)

with open("/app/history.jsonl", "w") as f:
    for entry in history:
        f.write(json.dumps(entry) + "\n")

print(f"Schedule written to /app/output.json ({len(final_schedule)} events)")
print(f"History written to /app/history.jsonl ({len(history)} API calls)")
print(f"Completed: {all_completed}, Missed: {list(missed_set)}")
