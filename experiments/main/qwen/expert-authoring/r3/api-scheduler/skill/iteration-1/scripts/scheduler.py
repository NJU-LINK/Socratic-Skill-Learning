#!/usr/bin/env python3
"""
General API Scheduler for the api-scheduler family.

Handles all variation axes:
  - task_volume (3-12 tasks, partial completion)
  - interruption_pattern (none, single, multiple emergencies)
  - priority_method (urgency, eisenhower, weighted)
  - scheduling_constraints (deadlines, dependencies, duplicate titles)
  - api_capability (basic, transient-errors, batch)

Usage:
  python3 scheduler.py [--tasks /app/tasks.json] [--simulator /app/api_simulator.py]
"""
import json
import subprocess
import os
import sys
import argparse

# ---------------------------------------------------------------------------
# Paths (overridable via CLI)
# ---------------------------------------------------------------------------
TASKS_FILE = "/app/tasks.json"
SIMULATOR = "/app/api_simulator.py"
OUTPUT_FILE = "/app/output.json"
HISTORY_FILE = "/app/history.jsonl"
STATE_FILE = "/tmp/calendar_state.json"

# Global history log – every (request, response) pair including retries.
history_log: list[dict] = []

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_time(t: str) -> int:
    """Convert 'HH:MM' to minutes from midnight."""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def format_time(mins: int) -> str:
    """Convert minutes from midnight to 'HH:MM'."""
    return f"{mins // 60:02d}:{mins % 60:02d}"


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------

def api_call(cmd: dict, max_retries: int = 10) -> dict:
    """Send one JSON command to the simulator; retry on transient errors.

    Every attempt (including errors) is recorded in history_log.
    Returns the first successful ('status':'ok') response.
    Raises RuntimeError if all retries are exhausted.
    """
    cmd_str = json.dumps(cmd) + "\n"
    env = {**os.environ, "SIM_STATE_FILE": STATE_FILE}
    for attempt in range(max_retries):
        result = subprocess.run(
            ["python3", SIMULATOR],
            input=cmd_str,
            capture_output=True,
            text=True,
            env=env,
        )
        output = result.stdout.strip()
        if not output:
            # Simulator produced no output – treat as transient and retry.
            continue
        # Take the last non-empty line as the response.
        lines = [l for l in output.split("\n") if l.strip()]
        response = json.loads(lines[-1])
        history_log.append({"request": cmd, "response": response})
        if response.get("status") == "ok":
            return response
        # Error response – retry (transient-error handling).
    raise RuntimeError(
        f"API call failed after {max_retries} attempts: {json.dumps(cmd)}"
    )


def check_batch_support() -> bool:
    """Return True if the simulator source exposes batch_insert."""
    try:
        with open(SIMULATOR) as f:
            return "batch_insert" in f.read()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

def compute_score(task: dict, method: str) -> float:
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


def priority_sort_key(task: dict, method: str, original_index: int):
    """Lower tuple = higher priority (sorted ascending)."""
    score = compute_score(task, method)
    deadline = task.get("deadline")
    # Tasks without a deadline sort after all tasks with one.
    deadline_val = parse_time(deadline) if deadline else float("inf")
    return (-score, deadline_val, original_index)


# ---------------------------------------------------------------------------
# Schedule builder (greedy, dependency-aware)
# ---------------------------------------------------------------------------

def build_schedule(
    indexed_tasks: list[tuple[int, dict]],
    config: dict,
    start_time: int,
    completed_ids: set | frozenset = frozenset(),
) -> tuple[list[dict], set[str]]:
    """Build a greedy schedule from *start_time*.

    Returns (scheduled_events, missed_task_ids).
    Each event dict has keys: task_id, title, start, end.
    """
    work_end = parse_time(config["work_end"])
    method = config.get("priority_method", "urgency")

    scheduled: list[dict] = []
    missed_ids: set[str] = set()
    scheduled_ids: set[str] = set(completed_ids)
    current_time = start_time
    remaining = list(indexed_tasks)

    # Safety bound to avoid infinite loops on pathological input.
    for _ in range(len(remaining) * 3 + 5):
        if not remaining:
            break

        # --- cascade: drop tasks whose deps include any missed task -------
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

        # --- find eligible tasks (all deps satisfied) ---------------------
        eligible = [
            (idx, task)
            for idx, task in remaining
            if all(d in scheduled_ids for d in task.get("depends_on", []))
        ]

        if not eligible:
            # All remaining are blocked by unresolvable deps → missed.
            for _, task in remaining:
                missed_ids.add(task["id"])
            break

        # --- pick best eligible task --------------------------------------
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
            scheduled.append(
                {
                    "task_id": best_task["id"],
                    "title": best_task["title"],
                    "start": format_time(current_time),
                    "end": format_time(end_time),
                }
            )
            scheduled_ids.add(best_task["id"])
            current_time = end_time
        else:
            missed_ids.add(best_task["id"])

    return scheduled, missed_ids


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=TASKS_FILE)
    parser.add_argument("--simulator", default=SIMULATOR)
    args = parser.parse_args()

    global TASKS_FILE, SIMULATOR
    TASKS_FILE = args.tasks
    SIMULATOR = args.simulator

    # ---- reset simulator state -------------------------------------------
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    # ---- load input ------------------------------------------------------
    with open(TASKS_FILE) as f:
        data = json.load(f)

    tasks: list[dict] = data["tasks"]
    emergencies: list[dict] = data.get("emergencies", [])
    config: dict = data["config"]
    calendar_id: str = config["calendar_id"]
    method: str = config.get("priority_method", "urgency")
    has_batch: bool = check_batch_support()

    # ---- build initial plan ----------------------------------------------
    indexed_tasks = list(enumerate(tasks))
    init_schedule, missed_ids = build_schedule(
        indexed_tasks, config, parse_time(config["work_start"])
    )

    # ---- clear calendar --------------------------------------------------
    api_call({"cmd": "clear", "calendar_id": calendar_id})

    # ---- insert initial events -------------------------------------------
    if has_batch and init_schedule:
        api_call(
            {
                "cmd": "batch_insert",
                "calendar_id": calendar_id,
                "events": [
                    {
                        "task_id": e["task_id"],
                        "title": e["title"],
                        "start": e["start"],
                        "end": e["end"],
                    }
                    for e in init_schedule
                ],
            }
        )
    else:
        for evt in init_schedule:
            api_call(
                {
                    "cmd": "insert",
                    "calendar_id": calendar_id,
                    "event": {
                        "task_id": evt["task_id"],
                        "title": evt["title"],
                        "start": evt["start"],
                        "end": evt["end"],
                    },
                }
            )

    # ---- tracking sets for status labels ---------------------------------
    initial_task_ids = {e["task_id"] for e in init_schedule}
    ever_rescheduled: set[str] = set()
    emergency_ids: set[str] = set()

    # ---- process emergencies chronologically -----------------------------
    emergencies.sort(key=lambda e: parse_time(e["arrival_time"]))

    for emergency in emergencies:
        arrival = parse_time(emergency["arrival_time"])

        # List current calendar events.
        resp = api_call({"cmd": "list", "calendar_id": calendar_id})
        current_events = resp.get("events", [])

        # Partition: preserved (end <= arrival) vs deleted (end > arrival).
        preserved = [e for e in current_events if parse_time(e["end"]) <= arrival]
        to_delete = [e for e in current_events if parse_time(e["end"]) > arrival]

        # Delete future/overlapping events from the calendar.
        for evt in to_delete:
            api_call(
                {
                    "cmd": "delete",
                    "calendar_id": calendar_id,
                    "event_id": evt["id"],
                }
            )

        # Insert emergency event.
        em_duration = emergency.get("duration_min", 0)
        em_end = arrival + em_duration
        em_task_id = emergency.get("id", emergency.get("task_id", "emergency"))
        api_call(
            {
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": {
                    "task_id": em_task_id,
                    "title": emergency["title"],
                    "start": format_time(arrival),
                    "end": format_time(em_end),
                },
            }
        )
        emergency_ids.add(em_task_id)

        # Completed task IDs = those in preserved events (normal tasks only).
        completed_ids: set[str] = set()
        for evt in preserved:
            tid = evt.get("task_id")
            if tid and tid not in emergency_ids:
                completed_ids.add(tid)

        # Remaining normal tasks = not yet completed.
        remaining_tasks = [
            (idx, task)
            for idx, task in enumerate(tasks)
            if task["id"] not in completed_ids
        ]

        # Rebuild schedule from emergency end time.
        new_schedule, missed_ids = build_schedule(
            remaining_tasks, config, em_end, completed_ids
        )

        # Insert rescheduled events.
        for evt in new_schedule:
            api_call(
                {
                    "cmd": "insert",
                    "calendar_id": calendar_id,
                    "event": {
                        "task_id": evt["task_id"],
                        "title": evt["title"],
                        "start": evt["start"],
                        "end": evt["end"],
                    },
                }
            )
            ever_rescheduled.add(evt["task_id"])

    # ---- assemble final output -------------------------------------------
    # Read final calendar state.
    resp = api_call({"cmd": "list", "calendar_id": calendar_id})
    final_events = resp.get("events", [])

    def get_status(task_id: str) -> str:
        if task_id in emergency_ids:
            return "emergency"
        if task_id in ever_rescheduled:
            return "rescheduled"
        return "scheduled"

    schedule_out = []
    for evt in final_events:
        tid = evt.get("task_id", "")
        schedule_out.append(
            {
                "task_id": tid,
                "title": evt.get("title", ""),
                "start": evt.get("start", ""),
                "end": evt.get("end", ""),
                "status": get_status(tid),
            }
        )

    # Sort chronologically.
    schedule_out.sort(key=lambda e: parse_time(e["start"]))

    # Completion summary (normal tasks only, excludes emergencies).
    completed = [
        e["task_id"]
        for e in schedule_out
        if e["status"] in ("scheduled", "rescheduled")
    ]
    all_normal_ids = [t["id"] for t in tasks]
    missed = [tid for tid in all_normal_ids if tid not in set(completed)]

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

    # ---- write output files ----------------------------------------------
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    with open(HISTORY_FILE, "w") as f:
        for entry in history_log:
            f.write(json.dumps(entry) + "\n")

    # ---- summary to stdout -----------------------------------------------
    print(f"Schedule built: {len(completed)} completed, {len(missed)} missed")
    print(f"  Completed: {completed}")
    print(f"  Missed:    {missed}")
    if emergency_ids:
        print(f"  Emergencies processed: {len(emergency_ids)}")


if __name__ == "__main__":
    main()
