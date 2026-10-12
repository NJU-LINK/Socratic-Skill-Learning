#!/usr/bin/env python3
"""
General API Scheduler for the api-scheduler skill family.

Reads /app/tasks.json, computes a priority-based schedule, interacts with
the calendar API simulator at /app/api_simulator.py, handles emergencies,
and writes /app/output.json + /app/history.jsonl.

Handles all spec axes:
- priority_method: urgency | eisenhower | weighted
- interruption_pattern: none | one | multiple emergencies
- scheduling_constraints: dependencies, deadlines, work windows
- api_capability: basic | transient-errors | batch
- task_volume: 3-12 tasks
"""
import json, subprocess, sys, os

HISTORY_FILE = "/app/history.jsonl"
OUTPUT_FILE = "/app/output.json"
TASKS_FILE = "/app/tasks.json"
SIMULATOR = "/app/api_simulator.py"


def call_api(cmd_dict):
    """Send one JSON command to the simulator, log to history, return response."""
    req_json = json.dumps(cmd_dict)
    result = subprocess.run(
        ["python3", SIMULATOR],
        input=req_json,
        capture_output=True,
        text=True,
        timeout=30
    )
    resp_line = result.stdout.strip()
    if not resp_line:
        resp = {"status": "error", "message": "Empty response from simulator"}
    else:
        resp = json.loads(resp_line)
    # Every attempt (including errors) goes to history
    entry = {"request": cmd_dict, "response": resp}
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return resp


def call_api_with_retry(cmd_dict, max_retries=10):
    """Call API, retrying on transient errors (rate limit, internal server error)."""
    for attempt in range(max_retries):
        resp = call_api(cmd_dict)
        if resp.get("status") == "ok":
            return resp
        msg = resp.get("message", "")
        transient = ("rate limit" in msg.lower()
                     or "internal server error" in msg.lower()
                     or "try again" in msg.lower())
        if transient:
            continue
        else:
            return resp
    return resp


def time_to_minutes(t):
    """Convert HH:MM string to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def minutes_to_time(m):
    """Convert minutes since midnight to HH:MM string."""
    return f"{m // 60:02d}:{m % 60:02d}"


def compute_score(task, method):
    """
    Compute priority score based on the method specified in config.
    - urgency: score = u
    - eisenhower: score = u * i
    - weighted: score = 0.6*u + 0.4*i  (or 0.5*u + 0.3*i + 0.2*t if team_priority present)
    """
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", 0)
    if method == "urgency":
        return u
    elif method == "eisenhower":
        return u * i
    elif method == "weighted":
        if "team_priority" in task:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
    return u


def make_sort_key(method, task_index_map):
    """
    Build a sort key function implementing the deterministic priority rules:
    1. Higher score first (negate for ascending sort)
    2. Earlier hard deadline first; no-deadline sorts after any deadline
    3. Input order (position in tasks.json) as final tiebreaker
    """
    def key(task):
        score = compute_score(task, method)
        deadline = task.get("deadline", None)
        idx = task_index_map[task["id"]]
        if deadline is not None:
            deadline_val = time_to_minutes(deadline)
            has_deadline = 0  # sorts before no-deadline
        else:
            deadline_val = 0
            has_deadline = 1  # sorts after tasks with deadlines
        return (-score, has_deadline, deadline_val, idx)
    return key


def build_schedule(tasks, method, start_time_str, work_end_str,
                   task_index_map, completed_ids, already_missed_ids):
    """
    Greedy priority-based scheduler with dependency awareness.

    Algorithm:
    - Sort remaining tasks by priority (score desc, deadline asc, input order).
    - For each task in priority order:
      - If any dependency is missed -> this task is missed (cascade).
      - If dependencies not yet scheduled -> defer to next round.
      - If task can't finish by work_end or its deadline -> missed.
      - Otherwise schedule at current_time, advance clock.
    - Repeat until no progress or all tasks resolved.

    Returns (scheduled_events_list, newly_missed_set).
    """
    completed_ids = set(completed_ids)
    missed_ids = set(already_missed_ids)
    current_time = time_to_minutes(start_time_str)
    work_end_min = time_to_minutes(work_end_str)
    schedule = []
    sort_key = make_sort_key(method, task_index_map)

    remaining = [t for t in tasks
                 if t["id"] not in completed_ids and t["id"] not in missed_ids]

    while remaining:
        made_progress = False
        next_remaining = []
        remaining.sort(key=sort_key)

        for task in remaining:
            tid = task["id"]
            deps = task.get("depends_on", [])
            deps_met = all(d in completed_ids for d in deps)
            deps_possible = all(d not in missed_ids for d in deps)

            if not deps_possible:
                # Cascade: prerequisite missed -> this task missed
                missed_ids.add(tid)
                made_progress = True
                continue

            if not deps_met:
                # Dependencies not yet placed; defer
                next_remaining.append(task)
                continue

            duration = task["duration_min"]
            end_time = current_time + duration
            deadline = task.get("deadline", None)

            if end_time > work_end_min:
                missed_ids.add(tid)
                made_progress = True
                continue

            if deadline is not None and end_time > time_to_minutes(deadline):
                missed_ids.add(tid)
                made_progress = True
                continue

            event = {
                "task_id": tid,
                "title": task["title"],
                "start": minutes_to_time(current_time),
                "end": minutes_to_time(end_time),
            }
            schedule.append(event)
            completed_ids.add(tid)
            current_time = end_time
            made_progress = True

        if not made_progress and next_remaining:
            # Deadlock: remaining tasks have unresolvable dependencies
            for task in next_remaining:
                missed_ids.add(task["id"])
            break

        remaining = next_remaining

    newly_missed = missed_ids - set(already_missed_ids)
    return schedule, newly_missed


def detect_batch_support():
    """Check if the simulator supports batch_insert by inspecting its source."""
    try:
        with open(SIMULATOR) as f:
            sim_code = f.read()
        return "batch_insert" in sim_code
    except Exception:
        return False


def main():
    # Initialize history (overwrite)
    with open(HISTORY_FILE, "w") as f:
        pass

    # Load task data
    with open(TASKS_FILE) as f:
        data = json.load(f)

    all_tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]

    work_start = config["work_start"]
    work_end = config["work_end"]
    priority_method = config["priority_method"]
    calendar_id = config["calendar_id"]

    # Build lookup structures
    task_index_map = {t["id"]: i for i, t in enumerate(all_tasks)}
    task_map = {t["id"]: t for t in all_tasks}
    normal_tasks = [t for t in all_tasks if t.get("type") != "emergency"]

    use_batch = detect_batch_support()

    # ── Step 1: Clear calendar (mandatory first mutation) ──
    resp = call_api({"cmd": "clear", "calendar_id": calendar_id})
    assert resp["status"] == "ok", f"Clear failed: {resp}"

    # ── Step 2: Build initial schedule ──
    schedule_events, initial_missed = build_schedule(
        normal_tasks, priority_method, work_start, work_end,
        task_index_map, completed_ids=set(), already_missed_ids=set()
    )

    # ── Step 3: Submit initial plan to API ──
    if use_batch and schedule_events:
        events_for_batch = [
            {"task_id": e["task_id"], "title": e["title"],
             "start": e["start"], "end": e["end"]}
            for e in schedule_events
        ]
        resp = call_api_with_retry({
            "cmd": "batch_insert",
            "calendar_id": calendar_id,
            "events": events_for_batch
        })
        if resp["status"] != "ok":
            use_batch = False  # fallback to individual inserts

    if not use_batch:
        for evt in schedule_events:
            call_api_with_retry({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"],
                    "title": evt["title"],
                    "start": evt["start"],
                    "end": evt["end"]
                }
            })

    # Track status per task_id: "scheduled" | "rescheduled" | "emergency"
    task_status = {e["task_id"]: "scheduled" for e in schedule_events}
    all_missed = set(initial_missed)

    # ── Step 4: Handle emergencies chronologically ──
    if emergencies:
        emergencies_sorted = sorted(
            emergencies, key=lambda e: time_to_minutes(e["arrival_time"])
        )

        for emergency in emergencies_sorted:
            arrival_min = time_to_minutes(emergency["arrival_time"])
            emergency_duration = emergency["duration_min"]
            emergency_end_min = arrival_min + emergency_duration

            # Get current calendar state
            resp = call_api({"cmd": "list", "calendar_id": calendar_id})
            current_events = resp.get("events", [])

            # Partition: preserve events ending <= arrival, delete the rest
            completed_so_far = set()
            interrupted_task_ids = set()

            for evt in current_events:
                evt_end_min = time_to_minutes(evt["end"])
                if evt_end_min <= arrival_min:
                    completed_so_far.add(evt["task_id"])
                else:
                    interrupted_task_ids.add(evt["task_id"])

            # Delete interrupted/future events
            for evt in current_events:
                if time_to_minutes(evt["end"]) > arrival_min:
                    call_api_with_retry({
                        "cmd": "delete",
                        "calendar_id": calendar_id,
                        "event_id": evt["id"]
                    })

            # Insert emergency at its arrival time
            emergency_event = {
                "task_id": emergency["id"],
                "title": emergency["title"],
                "start": minutes_to_time(arrival_min),
                "end": minutes_to_time(emergency_end_min),
            }
            call_api_with_retry({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": emergency_event
            })
            task_status[emergency["id"]] = "emergency"

            # Determine remaining normal tasks for rebuild
            remaining_normal = []
            for t in normal_tasks:
                tid = t["id"]
                if tid in completed_so_far:
                    continue  # already done
                if tid in interrupted_task_ids:
                    remaining_normal.append(t)  # back to pool at full duration
                elif tid not in all_missed:
                    remaining_normal.append(t)  # not yet attempted

            # Rebuild from emergency's end time
            new_schedule, new_missed = build_schedule(
                remaining_normal, priority_method,
                minutes_to_time(emergency_end_min), work_end,
                task_index_map, completed_ids=completed_so_far,
                already_missed_ids=all_missed
            )

            # Insert rebuilt events
            for evt in new_schedule:
                call_api_with_retry({
                    "cmd": "insert",
                    "calendar_id": calendar_id,
                    "event": {
                        "task_id": evt["task_id"],
                        "title": evt["title"],
                        "start": evt["start"],
                        "end": evt["end"]
                    }
                })
                task_status[evt["task_id"]] = "rescheduled"

            all_missed |= new_missed
            # Tasks that got rescheduled are no longer missed
            rescheduled_ids = {e["task_id"] for e in new_schedule}
            all_missed -= rescheduled_ids

    # ── Step 5: Verify final state ──
    resp = call_api({"cmd": "list", "calendar_id": calendar_id})
    final_events = resp.get("events", [])
    final_events_sorted = sorted(
        final_events, key=lambda e: time_to_minutes(e["start"])
    )

    # ── Step 6: Build output ──
    output_schedule = []
    for evt in final_events_sorted:
        tid = evt["task_id"]
        status = task_status.get(tid, "scheduled")
        output_schedule.append({
            "task_id": evt["task_id"],
            "title": evt["title"],
            "start": evt["start"],
            "end": evt["end"],
            "status": status
        })

    normal_task_ids = {t["id"] for t in normal_tasks}
    completed_ids = [e["task_id"] for e in output_schedule
                     if e["task_id"] in normal_task_ids]
    missed_ids = sorted([tid for tid in all_missed if tid in normal_task_ids])

    output = {
        "schedule": output_schedule,
        "completion_summary": {
            "completed": completed_ids,
            "missed": missed_ids,
            "total_tasks": len(normal_tasks),
            "completed_count": len(completed_ids),
            "missed_count": len(missed_ids)
        }
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print("Done!")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
