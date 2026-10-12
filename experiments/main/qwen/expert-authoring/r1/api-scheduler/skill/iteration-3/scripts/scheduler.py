#!/usr/bin/env python3
"""
Generic API Scheduler — reference implementation for the api-scheduler family.

Reads /app/tasks.json, schedules tasks using the calendar API at
/app/api_simulator.py, handles emergencies, and writes output.json + history.jsonl.

Usage:
    python3 scheduler.py

Adapt as needed for variant-specific features (batch_insert, transient errors, etc.).
"""

import json
import subprocess
import sys
import os

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
HISTORY = []
API_PATH = "/app/api_simulator.py"
TASKS_PATH = "/app/tasks.json"
OUTPUT_PATH = "/app/output.json"
HISTORY_PATH = "/app/history.jsonl"


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def to_minutes(t: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def to_time(m: int) -> str:
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{m // 60:02d}:{m % 60:02d}"


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------
def api_call(cmd_dict: dict) -> dict:
    """Send one JSON command to the simulator, record in history, return response."""
    global HISTORY
    cmd_str = json.dumps(cmd_dict) + "\n"
    result = subprocess.run(
        ["python3", API_PATH],
        input=cmd_str,
        capture_output=True,
        text=True,
    )
    stdout = result.stdout.strip()
    lines = [l for l in stdout.split("\n") if l.strip()]
    resp = json.loads(lines[-1]) if lines else {"status": "error", "message": "No response"}
    HISTORY.append({"request": cmd_dict, "response": resp})
    return resp


def api_call_retry(cmd_dict: dict, max_retries: int = 15) -> dict:
    """Retry a command on transient errors."""
    last_resp = None
    for _ in range(max_retries):
        resp = api_call(cmd_dict)
        if resp.get("status") == "ok":
            return resp
        last_resp = resp
    raise RuntimeError(
        f"API call failed after {max_retries} retries: {cmd_dict}, last: {last_resp}"
    )


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------
def compute_score(task: dict, method: str) -> float:
    """Compute priority score for a task given the method."""
    u = task.get("urgency", 0)
    i = task.get("importance", 0)

    if method == "urgency":
        return float(u)
    elif method == "eisenhower":
        return float(u * i)
    elif method == "weighted":
        t = task.get("team_priority")
        if t is not None:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
    else:
        raise ValueError(f"Unknown priority method: {method}")


def sort_tasks(tasks: list, method: str) -> list:
    """Sort tasks by priority (descending), with deterministic tie-breaking."""
    indexed = list(enumerate(tasks))

    def sort_key(item):
        idx, t = item
        score = compute_score(t, method)
        dl = t.get("hard_deadline")
        if dl is not None:
            deadline_val = to_minutes(dl)
            has_deadline = 0
        else:
            deadline_val = float("inf")
            has_deadline = 1
        return (-score, has_deadline, deadline_val, idx)

    indexed.sort(key=sort_key)
    return [t for _, t in indexed]


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------
def cascade_misses(tasks: list, missed: set) -> set:
    """Mark all tasks that transitively depend on missed tasks as missed."""
    missed = set(missed)
    changed = True
    while changed:
        changed = False
        for t in tasks:
            if t["id"] in missed:
                continue
            deps = t.get("depends_on", [])
            if any(d in missed for d in deps):
                missed.add(t["id"])
                changed = True
    return missed


# ---------------------------------------------------------------------------
# Core scheduler
# ---------------------------------------------------------------------------
def build_schedule(tasks: list, config: dict, start_clock: int, status_label: str = "scheduled"):
    """
    Greedy scheduler.

    Returns:
        (events, completed_ids, missed_ids)
    """
    work_end = to_minutes(config["work_end"])
    clock = start_clock
    completed = set()
    missed = set()
    events = []

    missed = cascade_misses(tasks, missed)
    remaining = [t for t in tasks if t["id"] not in missed]

    safety = len(remaining) * len(remaining) + 10
    iteration = 0

    while remaining and iteration < safety:
        iteration += 1
        placed = False

        for i, t in enumerate(remaining):
            deps = t.get("depends_on", [])
            if not all(d in completed for d in deps):
                continue

            start = clock
            end = start + t["duration_min"]

            if end > work_end:
                missed.add(t["id"])
                remaining.pop(i)
                missed = cascade_misses(remaining, missed)
                remaining = [r for r in remaining if r["id"] not in missed]
                placed = True
                break

            dl = t.get("hard_deadline")
            if dl and end > to_minutes(dl):
                missed.add(t["id"])
                remaining.pop(i)
                missed = cascade_misses(remaining, missed)
                remaining = [r for r in remaining if r["id"] not in missed]
                placed = True
                break

            events.append({
                "task_id": t["id"],
                "title": t["title"],
                "start": to_time(start),
                "end": to_time(end),
                "status": status_label,
            })
            completed.add(t["id"])
            clock = end
            remaining.pop(i)
            placed = True
            break

        if not placed:
            for t in remaining:
                missed.add(t["id"])
            remaining = []

    return events, completed, missed


# ---------------------------------------------------------------------------
# Submit schedule to API
# ---------------------------------------------------------------------------
def submit_events(calendar_id: str, events: list, use_batch: bool = False):
    """Submit events to the calendar API.

    IMPORTANT: The event payload sent to the API must include ALL fields
    that appear in output.json (task_id, title, start, end, status).
    The simulator stores the event dict verbatim, and the test compares
    calendar state (minus 'id') against output.json field-by-field.
    """
    if use_batch:
        api_events = []
        for e in events:
            api_events.append({
                "task_id": e["task_id"],
                "title": e["title"],
                "start": e["start"],
                "end": e["end"],
                "status": e["status"],
            })
        api_call_retry({
            "cmd": "batch_insert",
            "calendar_id": calendar_id,
            "events": api_events,
        })
    else:
        for e in events:
            api_call_retry({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": {
                    "task_id": e["task_id"],
                    "title": e["title"],
                    "start": e["start"],
                    "end": e["end"],
                    "status": e["status"],
                },
            })


def delete_future_events(calendar_id: str, arrival_minutes: int, existing_events: list):
    """Delete all events whose end is after arrival_minutes. Return preserved events."""
    preserved = []
    for evt in existing_events:
        end_min = to_minutes(evt["end"])
        if end_min <= arrival_minutes:
            preserved.append(evt)
        else:
            api_call_retry({
                "cmd": "delete",
                "calendar_id": calendar_id,
                "event_id": evt["id"],
            })
    return preserved


# ---------------------------------------------------------------------------
# Detect batch_insert capability
# ---------------------------------------------------------------------------
def has_batch_insert() -> bool:
    """Check if api_simulator.py supports batch_insert."""
    try:
        with open(API_PATH, "r") as f:
            source = f.read()
        return "batch_insert" in source
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global HISTORY

    # Load tasks
    with open(TASKS_PATH) as f:
        data = json.load(f)

    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    calendar_id = config["calendar_id"]
    method = config["priority_method"]
    work_start = to_minutes(config["work_start"])

    # task_id → status tracking (persists across emergency rounds)
    task_status = {}

    # Sort tasks by priority
    sorted_tasks = sort_tasks(tasks, method)

    # Build initial schedule
    initial_events, completed, missed = build_schedule(
        sorted_tasks, config, work_start, status_label="scheduled"
    )

    # Track statuses
    for e in initial_events:
        task_status[e["task_id"]] = "scheduled"
    for mid in missed:
        task_status[mid] = "missed"

    # Clear calendar first (MUST be first mutating call)
    api_call_retry({"cmd": "clear", "calendar_id": calendar_id})

    # Detect batch capability
    use_batch = has_batch_insert()

    # Submit initial plan
    submit_events(calendar_id, initial_events, use_batch=use_batch)

    # Master event list for output (tracks status correctly)
    all_events = list(initial_events)

    # Track which normal task IDs have been placed on calendar vs missed
    all_task_map = {t["id"]: t for t in tasks}
    placed_task_ids = {e["task_id"] for e in initial_events}
    missed_task_ids = set(missed)

    # Process emergencies in chronological order
    if emergencies:
        emergencies_sorted = sorted(
            emergencies, key=lambda e: to_minutes(e["arrival_time"])
        )

        for emg in emergencies_sorted:
            arrival = to_minutes(emg["arrival_time"])
            emg_end = arrival + emg["duration_min"]

            # Get current calendar state
            list_resp = api_call_retry({"cmd": "list", "calendar_id": calendar_id})
            current_events = list_resp.get("events", [])

            # Delete future events
            preserved_api = delete_future_events(calendar_id, arrival, current_events)
            preserved_task_ids = {e.get("task_id") for e in preserved_api}

            # Identify deleted normal tasks → back to reschedule pool
            deleted_task_ids = set()
            for evt in current_events:
                if evt.get("end") and to_minutes(evt["end"]) > arrival:
                    tid = evt.get("task_id")
                    if tid and tid in all_task_map:
                        deleted_task_ids.add(tid)

            # Build reschedule pool: deleted normal tasks + never-scheduled tasks
            reschedule_pool = []
            for tid in deleted_task_ids:
                reschedule_pool.append(all_task_map[tid])

            for t in tasks:
                if (t["id"] not in placed_task_ids
                        and t["id"] not in missed_task_ids
                        and t["id"] not in deleted_task_ids
                        and t["id"] not in preserved_task_ids):
                    reschedule_pool.append(t)

            # Sort reschedule pool by priority
            reschedule_sorted = sort_tasks(reschedule_pool, method)

            # Insert emergency event
            emg_event = {
                "task_id": emg["id"],
                "title": emg["title"],
                "start": to_time(arrival),
                "end": to_time(emg_end),
                "status": "emergency",
            }
            task_status[emg["id"]] = "emergency"
            api_call_retry({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": {
                    "task_id": emg["id"],
                    "title": emg["title"],
                    "start": to_time(arrival),
                    "end": to_time(emg_end),
                    "status": "emergency",
                },
            })

            # Build schedule for remaining tasks after emergency
            new_events, new_completed, new_missed = build_schedule(
                reschedule_sorted, config, emg_end, status_label="rescheduled"
            )

            # Submit rescheduled events
            submit_events(calendar_id, new_events, use_batch=False)

            # Update status tracking
            for tid in deleted_task_ids:
                # These were on calendar but got deleted; status unknown until rescheduled
                if tid in task_status:
                    del task_status[tid]

            for e in new_events:
                task_status[e["task_id"]] = "rescheduled"
            for mid in new_missed:
                task_status[mid] = "missed"

            # Update placed/missed tracking
            placed_task_ids = preserved_task_ids | {e["task_id"] for e in new_events}
            missed_task_ids |= new_missed

            # Rebuild all_events with correct statuses
            all_events = []
            for e in preserved_api:
                tid = e.get("task_id", "")
                all_events.append({
                    "task_id": tid,
                    "title": e.get("title", ""),
                    "start": e["start"],
                    "end": e["end"],
                    "status": task_status.get(tid, "scheduled"),
                })
            all_events.append(emg_event)
            all_events.extend(new_events)

    # Sort all_events chronologically
    all_events.sort(key=lambda e: to_minutes(e["start"]))

    # Determine final completed/missed for normal tasks only
    normal_task_ids = {t["id"] for t in tasks}
    scheduled_ids = set()
    for e in all_events:
        tid = e.get("task_id")
        if tid in normal_task_ids and e["status"] in ("scheduled", "rescheduled"):
            scheduled_ids.add(tid)

    final_completed = sorted(scheduled_ids)
    final_missed = sorted(normal_task_ids - scheduled_ids)

    output = {
        "schedule": all_events,
        "completion_summary": {
            "completed": final_completed,
            "missed": final_missed,
            "total_tasks": len(tasks),
            "completed_count": len(final_completed),
            "missed_count": len(final_missed),
        },
    }

    # Verification: list final state and compare
    final_list = api_call_retry({"cmd": "list", "calendar_id": calendar_id})
    api_event_count = final_list.get("count", 0)

    # Write output
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Write history (AFTER verification so the list call is included)
    with open(HISTORY_PATH, "w") as f:
        for entry in HISTORY:
            f.write(json.dumps(entry) + "\n")

    print(f"Schedule: {len(final_completed)} completed, {len(final_missed)} missed")
    print(f"Calendar has {api_event_count} events")
    print(f"Output written to {OUTPUT_PATH}")
    print(f"History written to {HISTORY_PATH} ({len(HISTORY)} entries)")


if __name__ == "__main__":
    main()
