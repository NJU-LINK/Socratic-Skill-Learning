#!/usr/bin/env python3
"""
Reusable API Scheduler for the api-scheduler family.

Handles all variation axes:
- task_volume: 3-12 tasks with completed/missed partition
- interruption_pattern: none, one, or multiple emergencies
- priority_method: urgency / eisenhower / weighted
- scheduling_constraints: work windows, deadlines, dependencies, infeasible tasks
- api_capability: basic / transient-errors / batch

Usage:
    python3 scheduler.py [--tasks-file TASKS_JSON] [--simulator SIMULATOR_PY]
                         [--history HISTORY_JSONL] [--output OUTPUT_JSON]
"""

import json
import subprocess
import sys
import os
import argparse
import copy


def parse_time(t):
    """Convert HH:MM to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def fmt_time(minutes):
    """Convert minutes since midnight to HH:MM."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def compute_score(task, priority_method):
    """Compute priority score based on the method specified.
    Rounds to 10 decimal places to avoid floating-point comparison issues."""
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    t = task.get("team_priority", None)

    if priority_method == "urgency":
        return round(float(u), 10)
    elif priority_method == "eisenhower":
        return round(float(u * i), 10)
    elif priority_method == "weighted":
        if t is not None:
            return round(0.5 * u + 0.3 * i + 0.2 * t, 10)
        else:
            return round(0.6 * u + 0.4 * i, 10)
    else:
        raise ValueError(f"Unknown priority method: {priority_method}")


def make_sort_key(task, idx):
    """
    Sort key for priority ordering.
    Higher score first, then earlier deadline, then input order.
    Tasks without deadline sort AFTER tasks with one.
    """
    score = task["_score"]
    deadline = task.get("deadline", None)

    # For deadline tie-break: tasks WITH deadline sort before tasks WITHOUT
    if deadline is not None:
        deadline_key = (0, parse_time(deadline))
    else:
        deadline_key = (1, float("inf"))

    return (-score, deadline_key, idx)


class APIClient:
    """Manages communication with the API simulator."""

    def __init__(self, simulator_path, calendar_id, history_path, max_retries=10):
        self.simulator_path = simulator_path
        self.calendar_id = calendar_id
        self.history_path = history_path
        self.max_retries = max_retries
        self.process = None
        self.history = []

    def start(self):
        """Start the simulator process."""
        self.process = subprocess.Popen(
            ["python3", self.simulator_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def stop(self):
        """Stop the simulator process."""
        if self.process:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def send(self, request, retry=True):
        """Send a request and return the response. Logs to history."""
        request["calendar_id"] = self.calendar_id
        attempts = 0
        while True:
            attempts += 1
            line = json.dumps(request) + "\n"
            self.process.stdin.write(line)
            self.process.stdin.flush()
            response_line = self.process.stdout.readline()
            if not response_line:
                stderr_out = self.process.stderr.read()
                raise RuntimeError(
                    f"Simulator process died. stderr: {stderr_out}"
                )
            response = json.loads(response_line.strip())

            # Log every attempt
            log_entry = {"request": copy.deepcopy(request), "response": response}
            self.history.append(log_entry)

            if response.get("status") == "ok":
                return response
            elif retry and attempts < self.max_retries:
                # Retry on errors (transient failures)
                continue
            else:
                return response

    def flush_history(self):
        """Write all history entries to the history file."""
        with open(self.history_path, "w") as f:
            for entry in self.history:
                f.write(json.dumps(entry) + "\n")

    def clear(self):
        """Clear the calendar. Must be first mutating call."""
        return self.send({"cmd": "clear"})

    def insert(self, event):
        """Insert an event into the calendar."""
        return self.send({"cmd": "insert", "event": event})

    def delete(self, event_id):
        """Delete an event from the calendar."""
        return self.send({"cmd": "delete", "event_id": event_id})

    def list_events(self):
        """List all events in the calendar."""
        return self.send({"cmd": "list"}, retry=False)

    def batch_insert(self, events):
        """Batch insert events (if supported by the simulator)."""
        return self.send({"cmd": "batch_insert", "events": events})


def build_schedule(tasks, config, pre_completed_ids=None, cursor_override=None):
    """
    Build a greedy schedule respecting priorities, dependencies, deadlines, and work windows.

    Algorithm (from simulator_intro.md):
    1. Start at config.work_start (or cursor_override if provided).
    2. Repeatedly choose the highest-priority remaining task whose depends_on
       tasks have already been scheduled or occur earlier in this same plan.
    3. Schedule it at the next free minute only if it finishes by both its hard
       deadline (when present) and config.work_end; otherwise mark it missed.
    4. If a prerequisite is missed, all tasks that still depend on it are missed.

    Args:
        tasks: list of task dicts to schedule
        config: dict with work_start, work_end, priority_method
        pre_completed_ids: set of task IDs already completed (for dependency checking)
        cursor_override: explicit start time in minutes (overrides config.work_start)

    Returns: (newly_scheduled_events, missed_task_ids)
    - newly_scheduled_events: list of NEW events (does not include pre-existing)
    - missed_task_ids: sorted list of task IDs that couldn't be scheduled
    """
    work_start = parse_time(config["work_start"])
    work_end = parse_time(config["work_end"])

    # Prepare tasks with metadata
    task_map = {}  # id -> task dict
    for idx, t in enumerate(tasks):
        t_copy = dict(t)
        t_copy["_score"] = compute_score(t_copy, config["priority_method"])
        t_copy["_idx"] = idx
        t_copy["_sort_key"] = make_sort_key(t_copy, idx)
        task_map[t["id"]] = t_copy

    # Track which task IDs are already completed (pre-existing)
    scheduled_ids = set()
    if pre_completed_ids:
        scheduled_ids = set(pre_completed_ids)

    missed = set()
    remaining_ids = set(t["id"] for t in tasks)

    # Current time cursor
    if cursor_override is not None:
        cursor = cursor_override
    else:
        cursor = work_start

    newly_scheduled = []

    # Greedy loop: repeatedly pick highest-priority ready task
    while remaining_ids:
        # Find ready tasks: deps all in scheduled_ids
        ready = []
        blocked_by_missed = []
        blocked_by_pending = []

        for tid in remaining_ids:
            task = task_map[tid]
            depends_on = task.get("depends_on", [])

            all_deps_scheduled = True
            any_dep_missed = False

            for dep_id in depends_on:
                if dep_id in scheduled_ids:
                    continue
                if dep_id in missed:
                    any_dep_missed = True
                    break
                if dep_id not in remaining_ids:
                    # dep is not scheduled, not missed, not remaining → impossible
                    any_dep_missed = True
                    break
                all_deps_scheduled = False

            if any_dep_missed:
                blocked_by_missed.append(tid)
            elif all_deps_scheduled:
                ready.append(tid)
            else:
                blocked_by_pending.append(tid)

        # Mark tasks blocked by missed prerequisites as missed
        if blocked_by_missed:
            for tid in blocked_by_missed:
                missed.add(tid)
                remaining_ids.discard(tid)
            continue  # Re-evaluate: new misses may cascade

        if not ready:
            # All remaining tasks are blocked by pending deps (circular or impossible)
            for tid in remaining_ids:
                missed.add(tid)
            remaining_ids.clear()
            break

        # Pick the highest-priority ready task
        ready.sort(key=lambda tid: task_map[tid]["_sort_key"])
        chosen_id = ready[0]
        task = task_map[chosen_id]
        duration = task["duration_min"]
        end_time = cursor + duration
        deadline = task.get("deadline", None)

        # Check if it fits
        fits = True
        if end_time > work_end:
            fits = False
        if deadline and end_time > parse_time(deadline):
            fits = False

        if fits:
            status = task.get("_status", "scheduled")
            new_event = {
                "task_id": chosen_id,
                "title": task["title"],
                "start": fmt_time(cursor),
                "end": fmt_time(end_time),
                "status": status,
            }
            newly_scheduled.append(new_event)
            scheduled_ids.add(chosen_id)
            remaining_ids.discard(chosen_id)
            cursor = end_time
        else:
            # Task doesn't fit → mark as missed
            missed.add(chosen_id)
            remaining_ids.discard(chosen_id)
            # Don't advance cursor; next task might fit

    return newly_scheduled, sorted(missed)


def handle_emergencies(tasks, config, emergencies, api_client):
    """
    Process emergencies and rebuild the schedule.

    For each emergency (in chronological order):
    1. Preserve events whose end <= arrival_time
    2. Delete events whose end > arrival_time (return to pool)
    3. Insert emergency at arrival_time
    4. Rebuild remaining normal tasks from emergency's end
    """
    work_start = parse_time(config["work_start"])
    work_end = parse_time(config["work_end"])

    # Build initial schedule
    initial_schedule, initial_missed = build_schedule(tasks, config)

    # Submit initial schedule to API
    api_client.clear()
    event_id_map = {}  # task_id -> event_id in calendar
    for evt in initial_schedule:
        resp = api_client.insert({
            "task_id": evt["task_id"],
            "title": evt["title"],
            "start": evt["start"],
            "end": evt["end"],
        })
        if resp.get("status") == "ok":
            event_id_map[evt["task_id"]] = resp.get("event_id")

    if not emergencies:
        return initial_schedule, initial_missed, event_id_map

    # Sort emergencies by arrival_time
    sorted_emergencies = sorted(emergencies, key=lambda e: parse_time(e["arrival_time"]))

    current_schedule = list(initial_schedule)
    # Track which normal tasks are still "active" (not yet permanently missed)
    # Initially, missed tasks are permanently missed
    permanently_missed = set(initial_missed)

    for emergency in sorted_emergencies:
        arrival = parse_time(emergency["arrival_time"])
        emergency_duration = emergency["duration_min"]
        emergency_end = arrival + emergency_duration

        # Step 1: Preserve events whose end <= arrival
        preserved = []
        to_delete = []
        for evt in current_schedule:
            evt_end = parse_time(evt["end"])
            if evt_end <= arrival:
                preserved.append(evt)
            else:
                to_delete.append(evt)

        # Step 2: Delete events from calendar whose end > arrival
        for evt in to_delete:
            tid = evt["task_id"]
            if tid in event_id_map:
                api_client.delete(event_id_map[tid])
                del event_id_map[tid]

        # Step 3: Collect interrupted normal task IDs (return to pool)
        returned_task_ids = set()
        for evt in to_delete:
            # Only normal tasks (scheduled/rescheduled) return to pool, not emergencies
            if evt.get("status") in ("scheduled", "rescheduled"):
                returned_task_ids.add(evt["task_id"])
            # Emergency events from previous rounds that are interrupted are just deleted

        # Remove returned tasks from permanently_missed (they get another chance)
        permanently_missed -= returned_task_ids

        # Step 4: Insert emergency at arrival time
        emergency_event = {
            "task_id": emergency["id"],
            "title": emergency["title"],
            "start": fmt_time(arrival),
            "end": fmt_time(emergency_end),
            "status": "emergency",
        }
        resp = api_client.insert({
            "task_id": emergency["id"],
            "title": emergency["title"],
            "start": fmt_time(arrival),
            "end": fmt_time(emergency_end),
        })
        if resp.get("status") == "ok":
            event_id_map[emergency["id"]] = resp.get("event_id")

        # Step 5: Rebuild remaining normal tasks from emergency end
        # Find which normal tasks are already completed (preserved events)
        completed_ids = set()
        for evt in preserved:
            if evt.get("status") in ("scheduled", "rescheduled"):
                completed_ids.add(evt["task_id"])

        # Build remaining task list: tasks not completed and not permanently missed
        remaining_tasks = []
        for t in tasks:
            if t["id"] not in completed_ids and t["id"] not in permanently_missed:
                t_copy = dict(t)
                if t["id"] in returned_task_ids:
                    t_copy["_status"] = "rescheduled"
                remaining_tasks.append(t_copy)

        # Build new schedule for remaining tasks starting at emergency_end
        rebuild_config = dict(config)
        rebuild_config["work_start"] = fmt_time(emergency_end)

        new_events, new_missed = build_schedule(
            remaining_tasks, rebuild_config,
            pre_completed_ids=completed_ids,
            cursor_override=emergency_end
        )

        # Submit new events to API
        for evt in new_events:
            if evt["task_id"] not in event_id_map:
                resp = api_client.insert({
                    "task_id": evt["task_id"],
                    "title": evt["title"],
                    "start": evt["start"],
                    "end": evt["end"],
                })
                if resp.get("status") == "ok":
                    event_id_map[evt["task_id"]] = resp.get("event_id")

        # Update current schedule
        current_schedule = preserved + [emergency_event] + new_events

        # Update permanently missed
        for m in new_missed:
            permanently_missed.add(m)

    # Final missed: normal tasks not in the final schedule
    scheduled_normal_ids = set(
        evt["task_id"] for evt in current_schedule
        if evt.get("status") in ("scheduled", "rescheduled")
    )
    final_missed = [t["id"] for t in tasks if t["id"] not in scheduled_normal_ids]

    return current_schedule, final_missed, event_id_map


def check_batch_support(simulator_path):
    """Check if the simulator supports batch_insert by inspecting its source."""
    with open(simulator_path, "r") as f:
        source = f.read()
    return "batch_insert" in source


def main():
    parser = argparse.ArgumentParser(description="API Scheduler")
    parser.add_argument("--tasks-file", default="/app/tasks.json")
    parser.add_argument("--simulator", default="/app/api_simulator.py")
    parser.add_argument("--history", default="/app/history.jsonl")
    parser.add_argument("--output", default="/app/output.json")
    args = parser.parse_args()

    # Load task data
    with open(args.tasks_file) as f:
        data = json.load(f)

    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    calendar_id = config["calendar_id"]

    # Start API client
    api = APIClient(args.simulator, calendar_id, args.history)
    api.start()

    try:
        # Check if batch_insert is needed/supported
        use_batch = check_batch_support(args.simulator)

        if not emergencies:
            # Simple case: no emergencies
            schedule, missed = build_schedule(tasks, config)

            # Clear calendar first
            api.clear()

            # Submit events
            if use_batch and schedule:
                events_for_batch = []
                for evt in schedule:
                    events_for_batch.append({
                        "task_id": evt["task_id"],
                        "title": evt["title"],
                        "start": evt["start"],
                        "end": evt["end"],
                    })
                api.batch_insert(events_for_batch)
            else:
                for evt in schedule:
                    api.insert({
                        "task_id": evt["task_id"],
                        "title": evt["title"],
                        "start": evt["start"],
                        "end": evt["end"],
                    })
        else:
            # Handle emergencies
            schedule, missed, event_id_map = handle_emergencies(
                tasks, config, emergencies, api
            )

        # Build output: strip internal 'status' field from schedule events
        # (calendar state only stores task_id, title, start, end)
        output_schedule = []
        for evt in schedule:
            output_schedule.append({
                "task_id": evt["task_id"],
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"],
            })

        # completion_summary.completed must be sorted alphabetically by task_id
        normal_completed = sorted([
            evt["task_id"] for evt in schedule
            if evt.get("status") in ("scheduled", "rescheduled")
        ])

        output = {
            "schedule": output_schedule,
            "completion_summary": {
                "completed": normal_completed,
                "missed": missed,
                "total_tasks": len(tasks),
                "completed_count": len(normal_completed),
                "missed_count": len(missed),
            },
        }

        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)

        # Flush history
        api.flush_history()

        print(f"Schedule written to {args.output}")
        print(f"History written to {args.history}")
        print(f"Completed: {normal_completed}")
        print(f"Missed: {missed}")

    finally:
        api.stop()


if __name__ == "__main__":
    main()
