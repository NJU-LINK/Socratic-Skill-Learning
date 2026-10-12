#!/usr/bin/env python3
"""
API Scheduler - Reusable solver for the calendar API scheduling family.

Reads /app/tasks.json, interacts with /app/api_simulator.py via stdin/stdout,
produces /app/output.json and /app/history.jsonl.

Handles all spec axes:
  - task_volume: 3-12 tasks
  - interruption_pattern: 0+ emergencies
  - priority_method: urgency, eisenhower, weighted
  - scheduling_constraints: work windows, deadlines, dependency DAGs, etc.
  - api_capability: basic, transient-errors, batch
"""

import json
import subprocess
import sys
import os
import copy

HISTORY = []
MAX_RETRIES = 50

def time_to_min(t_str):
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = t_str.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m):
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{m // 60:02d}:{m % 60:02d}"

def compute_score(task, method):
    """Compute priority score based on method."""
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
    Return a sort key for deterministic priority ordering.
    Higher score first → negate score.
    Tie-break 1: earlier hard deadline first; no deadline sorts AFTER tasks with deadline.
    Tie-break 2: earlier input order.
    """
    score = compute_score(task, method)
    deadline = task.get("deadline", None)
    
    # For deadline tie-break: tasks with deadline sort before tasks without.
    if deadline is not None:
        deadline_key = (0, time_to_min(deadline))
    else:
        deadline_key = (1, float('inf'))
    
    return (-score, deadline_key, original_index)

def send_command(proc, cmd):
    """Send a command to the simulator and get response. Retries on transient errors."""
    request_str = json.dumps(cmd)
    
    for attempt in range(MAX_RETRIES):
        proc.stdin.write(request_str + "\n")
        proc.stdin.flush()
        response_line = proc.stdout.readline().strip()
        
        if not response_line:
            raise RuntimeError(f"Simulator returned empty response for: {request_str}")
        
        response = json.loads(response_line)
        
        # Record every attempt in history
        HISTORY.append({"request": copy.deepcopy(cmd), "response": copy.deepcopy(response)})
        
        if response.get("status") == "ok":
            return response
        else:
            # Transient error - retry
            error_msg = response.get("message", "unknown error")
            if "Rate limit" in error_msg or "Internal server error" in error_msg or "Try again" in error_msg:
                continue
            else:
                # Non-transient error - return it anyway
                return response
    
    raise RuntimeError(f"Max retries exceeded for command: {request_str}")

def clear_calendar(proc, calendar_id):
    """Clear the calendar (must be first mutating operation)."""
    cmd = {"cmd": "clear", "calendar_id": calendar_id}
    resp = send_command(proc, cmd)
    if resp.get("status") != "ok":
        raise RuntimeError(f"Clear failed: {resp}")
    return resp

def insert_event(proc, calendar_id, event):
    """Insert an event into the calendar."""
    cmd = {"cmd": "insert", "calendar_id": calendar_id, "event": event}
    resp = send_command(proc, cmd)
    return resp

def batch_insert_events(proc, calendar_id, events):
    """Batch insert events if supported."""
    cmd = {"cmd": "batch_insert", "calendar_id": calendar_id, "events": events}
    resp = send_command(proc, cmd)
    return resp

def list_events(proc, calendar_id):
    """List all events in the calendar."""
    cmd = {"cmd": "list", "calendar_id": calendar_id}
    resp = send_command(proc, cmd)
    return resp

def delete_event(proc, calendar_id, event_id):
    """Delete an event from the calendar."""
    cmd = {"cmd": "delete", "calendar_id": calendar_id, "event_id": event_id}
    resp = send_command(proc, cmd)
    return resp

def greedy_schedule(tasks, method, work_start_min, work_end_min, current_time=None):
    """
    Greedy scheduling algorithm.
    
    Returns (scheduled, missed) where:
    - scheduled: list of (task, start_min, end_min) tuples
    - missed: list of task IDs
    
    Algorithm:
    1. Start at current_time (or work_start_min)
    2. Repeatedly choose highest-priority task whose dependencies are met
    3. If it fits before min(deadline, work_end), schedule it
    4. Otherwise mark it missed and continue trying lower-priority tasks
    5. If a prerequisite is missed, all dependents are missed
    """
    if current_time is None:
        current_time = work_start_min
    
    # Build task lookup with original indices
    task_list = []
    for idx, t in enumerate(tasks):
        task_list.append((t, idx))
    
    # Sort by priority
    task_list.sort(key=lambda x: sort_key(x[0], method, x[1]))
    
    scheduled = []
    missed = set()
    scheduled_ids = set()
    remaining = list(task_list)
    
    while remaining:
        made_progress = False
        next_remaining = []
        
        for task, orig_idx in remaining:
            task_id = task["id"]
            duration = task["duration_min"]
            deps = task.get("depends_on", [])
            deadline = task.get("deadline", None)
            
            # Check if any dependency is missed
            dep_missed = any(d in missed for d in deps)
            if dep_missed:
                missed.add(task_id)
                made_progress = True
                continue
            
            # Check if all dependencies are scheduled
            deps_met = all(d in scheduled_ids for d in deps)
            if not deps_met:
                next_remaining.append((task, orig_idx))
                continue
            
            # Check if task fits
            start = current_time
            end = start + duration
            
            # Must finish by work_end
            if end > work_end_min:
                missed.add(task_id)
                made_progress = True
                continue
            
            # Must finish by deadline if present
            if deadline is not None:
                deadline_min = time_to_min(deadline)
                if end > deadline_min:
                    missed.add(task_id)
                    made_progress = True
                    continue
            
            # Schedule it
            scheduled.append((task, start, end))
            scheduled_ids.add(task_id)
            current_time = end
            made_progress = True
        
        if not made_progress and next_remaining:
            # Deadlock: remaining tasks have unmet deps that aren't missed
            for task, orig_idx in next_remaining:
                missed.add(task["id"])
            break
        
        remaining = next_remaining
    
    missed_list = [t["id"] for t, _ in task_list if t["id"] in missed]
    return scheduled, missed_list

def main():
    # Read tasks
    with open("/app/tasks.json") as f:
        data = json.load(f)
    
    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    
    calendar_id = config["calendar_id"]
    work_start = config["work_start"]
    work_end = config["work_end"]
    method = config["priority_method"]
    
    work_start_min = time_to_min(work_start)
    work_end_min = time_to_min(work_end)
    
    # Start simulator
    proc = subprocess.Popen(
        [sys.executable, "/app/api_simulator.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    try:
        # Clear calendar first
        clear_calendar(proc, calendar_id)
        
        # Check if batch_insert is supported by inspecting simulator source
        use_batch = False
        try:
            with open("/app/api_simulator.py") as f:
                sim_source = f.read()
            if "batch_insert" in sim_source:
                use_batch = True
        except:
            pass
        
        # Sort emergencies by arrival_time
        emergencies_sorted = sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"]))
        
        # Build initial plan
        current_time = work_start_min
        all_scheduled = []  # (task, start, end, status)
        completed_ids = set()
        
        scheduled, missed_initial = greedy_schedule(
            tasks, method, work_start_min, work_end_min, current_time
        )
        
        # Submit initial plan to calendar
        initial_events = []
        for task, start, end in scheduled:
            event = {
                "task_id": task["id"],
                "title": task["title"],
                "start": min_to_time(start),
                "end": min_to_time(end)
            }
            initial_events.append(event)
            all_scheduled.append((task, start, end, "scheduled"))
            completed_ids.add(task["id"])
        
        if use_batch and initial_events:
            resp = batch_insert_events(proc, calendar_id, initial_events)
            if resp.get("status") != "ok":
                # Fall back to individual inserts
                for event in initial_events:
                    insert_event(proc, calendar_id, event)
        else:
            for event in initial_events:
                insert_event(proc, calendar_id, event)
        
        # Track pending tasks (not scheduled, not missed)
        missed_initial_set = set(missed_initial)
        pending_tasks = [t for t in tasks if t["id"] not in completed_ids and t["id"] not in missed_initial_set]
        reschedulable_ids = set(missed_initial)
        
        # Process emergencies
        for emergency in emergencies_sorted:
            arrival_min = time_to_min(emergency["arrival_time"])
            emergency_duration = emergency["duration_min"]
            emergency_end = arrival_min + emergency_duration
            
            # 1. Preserve events whose end <= arrival
            # 2. Delete events whose end > arrival
            list_resp = list_events(proc, calendar_id)
            current_events = list_resp.get("events", [])
            
            for evt in current_events:
                evt_end_min = time_to_min(evt["end"])
                if evt_end_min > arrival_min:
                    delete_event(proc, calendar_id, evt["id"])
                    # Return task to pending pool
                    task_id = evt.get("task_id")
                    if task_id:
                        completed_ids.discard(task_id)
                        reschedulable_ids.add(task_id)
                        all_scheduled = [(t, s, e, st) for t, s, e, st in all_scheduled if t["id"] != task_id]
            
            # Insert emergency
            emergency_event = {
                "task_id": emergency["id"],
                "title": emergency["title"],
                "start": emergency["arrival_time"],
                "end": min_to_time(emergency_end)
            }
            insert_event(proc, calendar_id, emergency_event)
            all_scheduled.append((emergency, arrival_min, emergency_end, "emergency"))
            
            # Rebuild remaining plan from emergency's end
            remaining_task_ids = reschedulable_ids | set(t["id"] for t in pending_tasks)
            remaining_tasks = [t for t in tasks if t["id"] in remaining_task_ids]
            
            current_time = emergency_end
            
            rescheduled, missed_resched = greedy_schedule(
                remaining_tasks, method, work_start_min, work_end_min, current_time
            )
            
            for task, start, end in rescheduled:
                event = {
                    "task_id": task["id"],
                    "title": task["title"],
                    "start": min_to_time(start),
                    "end": min_to_time(end)
                }
                insert_event(proc, calendar_id, event)
                all_scheduled.append((task, start, end, "rescheduled"))
                completed_ids.add(task["id"])
                reschedulable_ids.discard(task["id"])
            
            # Update for next emergency
            missed_resched_set = set(missed_resched)
            pending_tasks = [t for t in tasks if t["id"] not in completed_ids and t["id"] not in missed_resched_set]
            for mid in missed_resched:
                reschedulable_ids.discard(mid)
        
        # Build output
        schedule_output = []
        for task, start, end, status in all_scheduled:
            schedule_output.append({
                "task_id": task["id"],
                "title": task["title"],
                "start": min_to_time(start),
                "end": min_to_time(end),
                "status": status
            })
        
        # Sort by start time
        schedule_output.sort(key=lambda x: time_to_min(x["start"]))
        
        # Compute completion summary
        all_task_ids = set(t["id"] for t in tasks)
        completed_list = sorted([t["id"] for t in tasks if t["id"] in completed_ids])
        missed_list = sorted([tid for tid in all_task_ids if tid not in completed_ids])
        
        output = {
            "schedule": schedule_output,
            "completion_summary": {
                "completed": completed_list,
                "missed": missed_list,
                "total_tasks": len(tasks),
                "completed_count": len(completed_list),
                "missed_count": len(missed_list)
            }
        }
        
        # Write output
        with open("/app/output.json", "w") as f:
            json.dump(output, f, indent=2)
        
        # Write history
        with open("/app/history.jsonl", "w") as f:
            for entry in HISTORY:
                f.write(json.dumps(entry) + "\n")
        
        print("Done. Output written to /app/output.json")
        print(f"Completed: {completed_list}")
        print(f"Missed: {missed_list}")
        
    finally:
        proc.stdin.close()
        proc.wait()

if __name__ == "__main__":
    main()
