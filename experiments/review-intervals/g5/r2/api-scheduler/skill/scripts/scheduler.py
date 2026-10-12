#!/usr/bin/env python3
"""
General API Scheduler - handles the full api-scheduler family.

Reads tasks.json, computes priorities, schedules via API simulator,
handles emergencies, logs all interactions, writes output.json.

Handles:
- Priority methods: urgency, eisenhower, weighted (with/without team_priority)
- Dependencies (depends_on DAG)
- Hard deadlines
- Emergencies (chronological replanning)
- Transient errors (retry)
- Batch insertion (if supported by simulator)
- Tasks that don't fit -> missed, with cascade
"""

import json
import subprocess
import sys
import os

# --- Configuration ---
TASKS_FILE = "/app/tasks.json"
SIMULATOR = "/app/api_simulator.py"
HISTORY_FILE = "/app/history.jsonl"
OUTPUT_FILE = "/app/output.json"

history = []  # list of {"request": ..., "response": ...}

def time_to_min(t_str):
    """Convert HH:MM to minutes since midnight."""
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def min_to_time(m):
    """Convert minutes since midnight to HH:MM."""
    return f"{m // 60:02d}:{m % 60:02d}"

def call_simulator(request):
    """Send one command to the simulator, record in history, return response."""
    req_json = json.dumps(request)
    result = subprocess.run(
        ["python3", SIMULATOR],
        input=req_json + "\n",
        capture_output=True, text=True, timeout=30
    )
    response_line = result.stdout.strip()
    if not response_line:
        response = {"status": "error", "message": "No response from simulator"}
    else:
        response = json.loads(response_line)
    
    history.append({"request": request, "response": response})
    return response

def call_simulator_with_retry(request, max_retries=10):
    """Call simulator, retrying on transient errors."""
    for attempt in range(max_retries):
        response = call_simulator(request)
        if response.get("status") == "ok":
            return response
        msg = response.get("message", "").lower()
        if any(kw in msg for kw in ["rate limit", "internal server error", "try again", "transient"]):
            continue  # retry
        else:
            return response  # permanent error
    return response

def compute_score(task, priority_method):
    """Compute priority score based on the method."""
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", 0)
    
    if priority_method == "urgency":
        return u
    elif priority_method == "eisenhower":
        return u * i
    elif priority_method == "weighted":
        if "team_priority" in task:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
    else:
        raise ValueError(f"Unknown priority method: {priority_method}")

def sort_key_for_task(task, priority_method, original_index):
    """
    Return sort key: higher score first, earlier deadline first,
    earlier original index first.
    """
    score = compute_score(task, priority_method)
    deadline = task.get("deadline", None)
    if deadline is not None:
        dl = time_to_min(deadline)
    else:
        dl = float('inf')
    return (-score, dl, original_index)

def build_schedule(tasks, config, completed_ids=None, start_time_min=None, status_tag="scheduled"):
    """
    Build a schedule greedily:
    - Start at start_time_min (or config.work_start)
    - Repeatedly pick highest-priority task whose dependencies are satisfied
    - Schedule at next free minute if it fits (by deadline and work_end)
    - Otherwise mark missed; cascade to dependents

    Returns (events_list, missed_ids_set, final_time_min)
    """
    work_start = time_to_min(config["work_start"])
    work_end = time_to_min(config["work_end"])
    priority_method = config["priority_method"]

    if completed_ids is None:
        completed_ids = set()
    if start_time_min is None:
        start_time_min = work_start

    current_time = start_time_min
    events = []
    missed = set()
    completed = set(completed_ids)

    # Build task lookup and dependency map
    task_by_id = {t["id"]: t for t in tasks}
    task_index = {t["id"]: i for i, t in enumerate(tasks)}
    dep_map = {}
    for t in tasks:
        deps = t.get("depends_on", [])
        if isinstance(deps, str):
            deps = [deps]
        dep_map[t["id"]] = set(deps)

    # Remaining = all tasks not yet completed and not yet missed
    remaining = set(t["id"] for t in tasks) - completed

    while remaining:
        # Find ready tasks (all deps satisfied, none dep on a missed task)
        ready = []
        blocked = []
        for tid in remaining:
            if tid in missed:
                continue
            deps = dep_map.get(tid, set())
            # Check if any dependency is missed
            if deps & missed:
                missed.add(tid)
                continue
            if deps.issubset(completed):
                ready.append(tid)
            else:
                blocked.append(tid)

        if not ready:
            if blocked:
                # Deadlock - all blocked tasks are missed
                for tid in blocked:
                    missed.add(tid)
            break

        # Sort ready tasks by priority
        ready.sort(key=lambda tid: sort_key_for_task(task_by_id[tid], priority_method, task_index[tid]))

        # Pick highest priority
        chosen_id = ready[0]
        task = task_by_id[chosen_id]
        duration = task["duration_min"]
        end_time = current_time + duration

        # Check constraints
        deadline_ok = True
        if task.get("deadline") is not None:
            dl = time_to_min(task["deadline"])
            if end_time > dl:
                deadline_ok = False

        if end_time <= work_end and deadline_ok:
            event = {
                "task_id": task["id"],
                "title": task["title"],
                "start": min_to_time(current_time),
                "end": min_to_time(end_time),
                "status": status_tag
            }
            events.append(event)
            completed.add(task["id"])
            remaining.discard(task["id"])
            current_time = end_time
        else:
            # Mark as missed and cascade
            missed.add(chosen_id)
            remaining.discard(chosen_id)
            # Cascade: any task that depends on this is also missed
            cascade = True
            while cascade:
                cascade = False
                for tid in list(remaining):
                    if dep_map.get(tid, set()) & missed:
                        missed.add(tid)
                        remaining.discard(tid)
                        cascade = True

    return events, missed, current_time

def check_batch_insert_supported():
    """Check if the simulator supports batch_insert by inspecting the source."""
    try:
        with open(SIMULATOR) as f:
            source = f.read()
        return "batch_insert" in source
    except Exception:
        return False

def main():
    # Load tasks
    with open(TASKS_FILE) as f:
        data = json.load(f)

    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    calendar_id = config["calendar_id"]
    priority_method = config["priority_method"]

    use_batch = check_batch_insert_supported()

    # Step 1: Clear the calendar
    resp = call_simulator_with_retry({"cmd": "clear", "calendar_id": calendar_id})
    assert resp["status"] == "ok", f"Clear failed: {resp}"

    # Step 2: Build initial schedule
    scheduled_events, missed_ids, _ = build_schedule(tasks, config, status_tag="scheduled")

    # Step 3: Insert initial events into simulator
    if use_batch and scheduled_events:
        batch_events = []
        for evt in scheduled_events:
            batch_events.append({
                "task_id": evt["task_id"],
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"],
                "status": evt["status"]
            })
        resp = call_simulator_with_retry({
            "cmd": "batch_insert",
            "calendar_id": calendar_id,
            "events": batch_events
        })
        if resp["status"] != "ok":
            # Fallback to individual inserts
            for evt in scheduled_events:
                call_simulator_with_retry({
                    "cmd": "insert",
                    "calendar_id": calendar_id,
                    "event": {
                        "task_id": evt["task_id"],
                        "title": evt["title"],
                        "start": evt["start"],
                        "end": evt["end"],
                        "status": evt["status"]
                    }
                })
    else:
        for evt in scheduled_events:
            resp = call_simulator_with_retry({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"],
                    "title": evt["title"],
                    "start": evt["start"],
                    "end": evt["end"],
                    "status": evt["status"]
                }
            })
            assert resp["status"] == "ok", f"Insert failed for {evt['task_id']}: {resp}"

    # Track all events in calendar (for emergency handling)
    all_calendar_events = list(scheduled_events)
    task_by_id = {t["id"]: t for t in tasks}

    # Step 4: Handle emergencies in chronological order
    emergencies_sorted = sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"]))

    for emergency in emergencies_sorted:
        arrival = time_to_min(emergency["arrival_time"])
        emergency_duration = emergency["duration_min"]
        emergency_end = arrival + emergency_duration

        # Guard: emergency must finish by work_end (and its deadline if present)
        work_end = time_to_min(config["work_end"])
        emergency_deadline = emergency.get("deadline")
        if emergency_deadline is not None:
            effective_deadline = min(time_to_min(emergency_deadline), work_end)
        else:
            effective_deadline = work_end
        
        if emergency_end > effective_deadline:
            print(f"WARNING: Emergency '{emergency.get('title', 'unknown')}' ends at "
                  f"{min_to_time(emergency_end)} which exceeds constraint "
                  f"{min_to_time(effective_deadline)}")

        # 1. Preserve events whose end <= arrival
        preserved = []
        interrupted = []
        for evt in all_calendar_events:
            if evt["status"] == "emergency":
                # Previous emergencies are already placed
                if time_to_min(evt["end"]) <= arrival:
                    preserved.append(evt)
                else:
                    preserved.append(evt)
                continue
            evt_end = time_to_min(evt["end"])
            if evt_end <= arrival:
                preserved.append(evt)
            else:
                interrupted.append(evt)

        # 2. Delete interrupted events from calendar
        list_resp = call_simulator({"cmd": "list", "calendar_id": calendar_id})
        current_events = list_resp.get("events", [])
        task_to_evt_id = {}
        for ce in current_events:
            if "task_id" in ce:
                task_to_evt_id[ce["task_id"]] = ce["id"]

        for evt in interrupted:
            evt_id = task_to_evt_id.get(evt["task_id"])
            if evt_id:
                call_simulator_with_retry({
                    "cmd": "delete",
                    "calendar_id": calendar_id,
                    "event_id": evt_id
                })

        # 3. Insert the emergency
        emergency_task_id = emergency.get("id", emergency.get("task_id", "EMERGENCY"))
        emergency_event = {
            "task_id": emergency_task_id,
            "title": emergency["title"],
            "start": emergency["arrival_time"],
            "end": min_to_time(emergency_end),
            "status": "emergency"
        }

        call_simulator_with_retry({
            "cmd": "insert",
            "calendar_id": calendar_id,
            "event": {
                "task_id": emergency_task_id,
                "title": emergency["title"],
                "start": emergency["arrival_time"],
                "end": min_to_time(emergency_end),
                "status": "emergency"
            }
        })

        # 4. Rebuild remaining normal plan from emergency end
        # Completed = tasks in preserved events (non-emergency)
        completed_now = set()
        for evt in preserved:
            if evt["status"] != "emergency":
                completed_now.add(evt["task_id"])

        # Rebuild: schedule remaining tasks starting from emergency_end
        new_events, new_missed, _ = build_schedule(
            tasks, config,
            completed_ids=completed_now,
            start_time_min=emergency_end,
            status_tag="rescheduled"
        )

        # Insert new events
        for evt in new_events:
            call_simulator_with_retry({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"],
                    "title": evt["title"],
                    "start": evt["start"],
                    "end": evt["end"],
                    "status": evt["status"]
                }
            })

        # Update calendar state
        all_calendar_events = preserved + [emergency_event] + new_events

    # Step 5: Verify with list
    final_list = call_simulator({"cmd": "list", "calendar_id": calendar_id})

    # Step 6: Build output
    # completed and missed must be sorted alphabetically for test compatibility
    completed_ids = sorted(
        t["id"] for t in tasks
        if any(evt["task_id"] == t["id"] and evt["status"] != "emergency"
               for evt in all_calendar_events)
    )
    missed_ids_final = sorted(
        t["id"] for t in tasks
        if t["id"] not in completed_ids
    )

    output = {
        "schedule": all_calendar_events,
        "completion_summary": {
            "completed": completed_ids,
            "missed": missed_ids_final,
            "total_tasks": len(tasks),
            "completed_count": len(completed_ids),
            "missed_count": len(missed_ids_final)
        }
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    # Write history
    with open(HISTORY_FILE, "w") as f:
        for entry in history:
            f.write(json.dumps(entry) + "\n")

    print(f"Schedule: {len(all_calendar_events)} events")
    print(f"Completed: {completed_ids}")
    print(f"Missed: {missed_ids_final}")

if __name__ == "__main__":
    main()
