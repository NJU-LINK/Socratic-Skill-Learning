#!/usr/bin/env python3
"""
API Scheduler - generalized scheduling script for all family variants.
Reads /app/tasks.json, computes a priority schedule, interacts with the
calendar API simulator, handles emergencies, and writes output artifacts.

Usage: python3 /app/scripts/schedule.py
"""

import json
import subprocess
import sys
import os

TASKS_FILE = "/app/tasks.json"
HISTORY_FILE = "/app/history.jsonl"
OUTPUT_FILE = "/app/output.json"
SIMULATOR = "/app/api_simulator.py"
MAX_RETRIES = 30


def parse_time(t):
    """Convert 'HH:MM' to minutes from midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def fmt_time(minutes):
    """Convert minutes from midnight to 'HH:MM'."""
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


class CalendarAPI:
    """Wraps the calendar API simulator with logging and retry logic."""

    def __init__(self, calendar_id, history_path):
        self.calendar_id = calendar_id
        self.history_path = history_path
        self.history_file = open(history_path, "w")
        self.has_batch = self._detect_batch()

    def _detect_batch(self):
        """Check if api_simulator.py supports batch_insert."""
        try:
            with open(SIMULATOR, "r") as f:
                return "batch_insert" in f.read()
        except FileNotFoundError:
            return False

    def send(self, cmd, retry_on_error=True):
        """Send a command; retry transient errors up to MAX_RETRIES."""
        response = None
        for attempt in range(MAX_RETRIES if retry_on_error else 1):
            response = self._send_once(cmd)
            if response.get("status") == "ok" or not retry_on_error:
                return response
        return response

    def _send_once(self, cmd):
        """Send a single command and log the request/response pair."""
        proc = subprocess.run(
            [sys.executable, SIMULATOR],
            input=json.dumps(cmd) + "\n",
            capture_output=True,
            text=True,
        )
        try:
            response = json.loads(proc.stdout.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError):
            response = {"status": "error", "message": proc.stdout + proc.stderr}
        pair = {"request": cmd, "response": response}
        self.history_file.write(json.dumps(pair) + "\n")
        self.history_file.flush()
        return response

    def clear(self):
        return self.send({"cmd": "clear", "calendar_id": self.calendar_id})

    def insert(self, event):
        return self.send({
            "cmd": "insert",
            "calendar_id": self.calendar_id,
            "event": event,
        })

    def batch_insert(self, events):
        return self.send({
            "cmd": "batch_insert",
            "calendar_id": self.calendar_id,
            "events": events,
        })

    def delete(self, event_id):
        return self.send({
            "cmd": "delete",
            "calendar_id": self.calendar_id,
            "event_id": event_id,
        })

    def list_events(self):
        return self.send(
            {"cmd": "list", "calendar_id": self.calendar_id},
            retry_on_error=False,
        )

    def close(self):
        self.history_file.close()


def compute_score(task, method):
    """Compute priority score for a task."""
    u = task.get("urgency", 0)
    i = task.get("importance", 0)
    if method == "urgency":
        return float(u)
    elif method == "eisenhower":
        return float(u * i)
    elif method == "weighted":
        if "team_priority" in task:
            return 0.5 * u + 0.3 * i + 0.2 * task["team_priority"]
        else:
            return 0.6 * u + 0.4 * i
    return float(u)


def sort_key(task, method, index):
    """
    Sort key for task ordering (lower = higher priority).
    Tie-breaking: higher score → earlier deadline → input order.
    """
    score = compute_score(task, method)
    deadline = task.get("deadline")
    if deadline is not None and deadline != "":
        deadline_val = parse_time(deadline)
        has_deadline = 0  # deadline tasks sort before no-deadline
    else:
        deadline_val = float("inf")
        has_deadline = 1
    return (-score, has_deadline, deadline_val, index)


def build_schedule(tasks, task_indices, method, start_time, work_end,
                   completed_ids=None):
    """
    Greedy priority scheduling with dependency awareness.

    Returns (scheduled, missed) lists.
    """
    if completed_ids is None:
        completed_ids = set()

    remaining = list(tasks)
    scheduled = []
    missed = []
    current_time = start_time

    while remaining:
        # Find candidates whose dependencies are all satisfied
        candidates = []
        for task in remaining:
            deps = task.get("depends_on", []) or []
            if all(d in completed_ids for d in deps):
                candidates.append(task)

        if not candidates:
            # All remaining have unresolvable dependencies → missed
            for task in remaining:
                missed.append({**task, "status": "missed"})
            break

        # Sort by priority (descending), tie-break by deadline then index
        candidates.sort(
            key=lambda t: sort_key(t, method, task_indices.get(t["id"], 999))
        )
        task = candidates[0]
        remaining.remove(task)

        task_start = current_time
        task_end = task_start + task["duration_min"]

        # Feasibility: must finish by work_end and deadline (if any)
        feasible = True
        if task_end > work_end:
            feasible = False
        deadline = task.get("deadline")
        if deadline and deadline != "":
            if task_end > parse_time(deadline):
                feasible = False

        if feasible:
            scheduled.append({
                **task,
                "start": fmt_time(task_start),
                "end": fmt_time(task_end),
            })
            completed_ids.add(task["id"])
            current_time = task_end
        else:
            missed.append({**task, "status": "missed"})
            # NOT added to completed_ids → dependents cascade to missed

    return scheduled, missed


def main():
    # ── Load inputs ──────────────────────────────────────────────────────
    with open(TASKS_FILE) as f:
        data = json.load(f)

    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]

    calendar_id = config["calendar_id"]
    method = config["priority_method"]
    work_start = parse_time(config["work_start"])
    work_end = parse_time(config["work_end"])
    task_indices = {t["id"]: i for i, t in enumerate(tasks)}
    all_normal_ids = [t["id"] for t in tasks]
    normal_id_set = set(all_normal_ids)

    # ── Initialize API ───────────────────────────────────────────────────
    api = CalendarAPI(calendar_id, HISTORY_FILE)
    api.clear()  # First mutating command must be clear

    # ── Build and submit initial plan ────────────────────────────────────
    scheduled, missed_initial = build_schedule(
        tasks, task_indices, method, work_start, work_end
    )

    event_ids = []
    if api.has_batch and len(scheduled) > 1:
        events = [
            {
                "task_id": t["id"],
                "title": t["title"],
                "start": t["start"],
                "end": t["end"],
            }
            for t in scheduled
        ]
        resp = api.batch_insert(events)
        if resp.get("status") != "ok":
            # Fallback to individual inserts
            event_ids = []
            for t in scheduled:
                resp = api.insert({
                    "task_id": t["id"],
                    "title": t["title"],
                    "start": t["start"],
                    "end": t["end"],
                })
                event_ids.append(resp.get("event_id", ""))
        else:
            if "event_ids" in resp:
                event_ids = resp["event_ids"]
            else:
                list_resp = api.list_events()
                event_ids = [e["id"] for e in list_resp.get("events", [])]
    else:
        for t in scheduled:
            resp = api.insert({
                "task_id": t["id"],
                "title": t["title"],
                "start": t["start"],
                "end": t["end"],
            })
            event_ids.append(resp.get("event_id", ""))

    missed_ids = {t["id"] for t in missed_initial}

    # ── Handle emergencies ───────────────────────────────────────────────
    if emergencies:
        # Track calendar state as list of event dicts
        calendar = []
        for i, task in enumerate(scheduled):
            calendar.append({
                "task_id": task["id"],
                "title": task["title"],
                "start": task["start"],
                "end": task["end"],
                "event_id": event_ids[i],
                "status": "scheduled",
                "is_emergency": False,
            })

        sorted_emgs = sorted(
            emergencies, key=lambda e: parse_time(e["arrival_time"])
        )
        completed_normal_ids = set()

        for emg in sorted_emgs:
            arrival = parse_time(emg["arrival_time"])

            # Preserve events ending at or before arrival
            preserved = []
            to_delete = []
            for evt in calendar:
                if parse_time(evt["end"]) <= arrival:
                    preserved.append(evt)
                    if not evt["is_emergency"]:
                        completed_normal_ids.add(evt["task_id"])
                else:
                    to_delete.append(evt)

            # Delete events ending after arrival
            for evt in to_delete:
                api.delete(evt["event_id"])

            # Insert emergency at arrival time
            emg_start = arrival
            emg_end = emg_start + emg["duration_min"]
            resp = api.insert({
                "task_id": emg["id"],
                "title": emg["title"],
                "start": fmt_time(emg_start),
                "end": fmt_time(emg_end),
            })
            emg_eid = resp.get("event_id", "")

            calendar = preserved + [{
                "task_id": emg["id"],
                "title": emg["title"],
                "start": fmt_time(emg_start),
                "end": fmt_time(emg_end),
                "event_id": emg_eid,
                "status": "emergency",
                "is_emergency": True,
            }]

            # Find remaining normal tasks to reschedule
            scheduled_normal_ids = {
                e["task_id"] for e in calendar if not e["is_emergency"]
            }
            remaining_normal = [
                t for t in tasks
                if t["id"] not in completed_normal_ids
                and t["id"] not in scheduled_normal_ids
                and t["id"] not in missed_ids
            ]

            # Rebuild from emergency's end
            rebuild_start = emg_end
            if remaining_normal:
                rescheduled, new_missed = build_schedule(
                    remaining_normal,
                    task_indices,
                    method,
                    rebuild_start,
                    work_end,
                    completed_ids=set(completed_normal_ids),
                )
                for task in rescheduled:
                    resp = api.insert({
                        "task_id": task["id"],
                        "title": task["title"],
                        "start": task["start"],
                        "end": task["end"],
                    })
                    eid = resp.get("event_id", "")
                    calendar.append({
                        "task_id": task["id"],
                        "title": task["title"],
                        "start": task["start"],
                        "end": task["end"],
                        "event_id": eid,
                        "status": "rescheduled",
                        "is_emergency": False,
                    })
                for task in new_missed:
                    missed_ids.add(task["id"])

        final_schedule = sorted(
            [
                {
                    "task_id": e["task_id"],
                    "title": e["title"],
                    "start": e["start"],
                    "end": e["end"],
                    "status": e["status"],
                }
                for e in calendar
            ],
            key=lambda e: parse_time(e["start"]),
        )
    else:
        final_schedule = [
            {
                "task_id": t["id"],
                "title": t["title"],
                "start": t["start"],
                "end": t["end"],
                "status": "scheduled",
            }
            for t in scheduled
        ]

    # ── Verify final state ───────────────────────────────────────────────
    api.list_events()

    # ── Write output ─────────────────────────────────────────────────────
    scheduled_normal = [
        e["task_id"] for e in final_schedule if e["task_id"] in normal_id_set
    ]
    missed_final = [
        tid for tid in all_normal_ids if tid not in set(scheduled_normal)
    ]

    output = {
        "schedule": final_schedule,
        "completion_summary": {
            "completed": scheduled_normal,
            "missed": missed_final,
            "total_tasks": len(tasks),
            "completed_count": len(scheduled_normal),
            "missed_count": len(missed_final),
        },
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    api.close()
    print(f"Schedule written to {OUTPUT_FILE}")
    print(f"History written to {HISTORY_FILE}")
    print(f"Completed: {output['completion_summary']['completed']}")
    print(f"Missed: {output['completion_summary']['missed']}")


if __name__ == "__main__":
    main()
