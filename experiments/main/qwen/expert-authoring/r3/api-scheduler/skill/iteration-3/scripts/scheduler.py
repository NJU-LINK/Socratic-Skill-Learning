#!/usr/bin/env python3
"""General API Scheduler for the api-scheduler family.

Handles all variation axes:
  - task_volume (3-12 tasks, partial completion)
  - interruption_pattern (none, single, multiple emergencies)
  - priority_method (urgency, eisenhower, weighted)
  - scheduling_constraints (deadlines, dependencies, duplicate titles)
  - api_capability (basic, transient-errors, batch)

Usage:
  cp scheduler.py /app/solve.py
  cd /app && rm -f /tmp/calendar_state.json && python3 solve.py

Note: The full source is also embedded in SKILL.md §10 so the agent can
write it directly without filesystem access to the skill package.
"""
import json, subprocess, os, sys

TASKS_FILE = "/app/tasks.json"
SIMULATOR = "/app/api_simulator.py"
OUTPUT_FILE = "/app/output.json"
HISTORY_FILE = "/app/history.jsonl"
STATE_FILE = "/tmp/calendar_state.json"
history_log = []

def parse_time(t):
    h, m = map(int, t.split(":"))
    return h * 60 + m

def format_time(mins):
    return f"{mins // 60:02d}:{mins % 60:02d}"

def api_call(cmd, max_retries=10):
    """Send one JSON command; retry on transient errors. Logs every attempt."""
    cmd_str = json.dumps(cmd) + "\n"
    env = {**os.environ, "SIM_STATE_FILE": STATE_FILE}
    for _ in range(max_retries):
        result = subprocess.run(
            ["python3", SIMULATOR],
            input=cmd_str, capture_output=True, text=True, env=env,
        )
        output = result.stdout.strip()
        if not output:
            continue
        lines = [l for l in output.split("\n") if l.strip()]
        response = json.loads(lines[-1])
        history_log.append({"request": cmd, "response": response})
        if response.get("status") == "ok":
            return response
    raise RuntimeError(f"API call failed after {max_retries} retries: {json.dumps(cmd)}")

def check_batch_support():
    try:
        with open(SIMULATOR) as f:
            return "batch_insert" in f.read()
    except OSError:
        return False

def compute_score(task, method):
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

def priority_sort_key(task, method, original_index):
    """Lower tuple = higher priority (sorted ascending)."""
    score = compute_score(task, method)
    deadline = task.get("deadline")
    deadline_val = parse_time(deadline) if deadline else float("inf")
    return (-score, deadline_val, original_index)

def build_schedule(indexed_tasks, config, start_time, completed_ids=frozenset()):
    """Greedy dependency-aware scheduler. Returns (events, missed_ids)."""
    work_end = parse_time(config["work_end"])
    method = config.get("priority_method", "urgency")
    scheduled = []
    missed_ids = set()
    scheduled_ids = set(completed_ids)
    current_time = start_time
    remaining = list(indexed_tasks)

    for _ in range(len(remaining) * 3 + 5):
        if not remaining:
            break
        # Cascade-drop tasks whose deps include a missed task
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
        # Eligible = all deps satisfied
        eligible = [
            (idx, task) for idx, task in remaining
            if all(d in scheduled_ids for d in task.get("depends_on", []))
        ]
        if not eligible:
            for _, task in remaining:
                missed_ids.add(task["id"])
            break
        # Pick best eligible task
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
            # build_schedule returns bare events; status is added at insert time
            scheduled.append({
                "task_id": best_task["id"],
                "title": best_task["title"],
                "start": format_time(current_time),
                "end": format_time(end_time),
            })
            scheduled_ids.add(best_task["id"])
            current_time = end_time
        else:
            missed_ids.add(best_task["id"])
    return scheduled, missed_ids

def main():
    # Reset simulator state — critical for clean runs
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    with open(TASKS_FILE) as f:
        data = json.load(f)
    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    calendar_id = config["calendar_id"]
    has_batch = check_batch_support()

    # Build initial plan
    indexed_tasks = list(enumerate(tasks))
    init_schedule, missed_ids = build_schedule(
        indexed_tasks, config, parse_time(config["work_start"])
    )

    # Clear calendar (must be first mutating call)
    api_call({"cmd": "clear", "calendar_id": calendar_id})

    # Insert initial events (include status so calendar state matches output)
    if has_batch and init_schedule:
        api_call({
            "cmd": "batch_insert", "calendar_id": calendar_id,
            "events": [
                {"task_id": e["task_id"], "title": e["title"],
                 "start": e["start"], "end": e["end"],
                 "status": "scheduled"}
                for e in init_schedule
            ],
        })
    else:
        for evt in init_schedule:
            api_call({
                "cmd": "insert", "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"], "title": evt["title"],
                    "start": evt["start"], "end": evt["end"],
                    "status": "scheduled",
                },
            })

    # Tracking sets for status labels
    ever_rescheduled = set()
    emergency_ids = set()

    # Process emergencies chronologically
    emergencies.sort(key=lambda e: parse_time(e["arrival_time"]))
    for emergency in emergencies:
        arrival = parse_time(emergency["arrival_time"])
        resp = api_call({"cmd": "list", "calendar_id": calendar_id})
        current_events = resp.get("events", [])

        # Partition: preserved vs to-delete
        preserved = [e for e in current_events if parse_time(e["end"]) <= arrival]
        to_delete = [e for e in current_events if parse_time(e["end"]) > arrival]

        # Delete future/overlapping events using their event id
        for evt in to_delete:
            api_call({
                "cmd": "delete", "calendar_id": calendar_id,
                "event_id": evt["id"],
            })

        # Insert emergency
        em_duration = emergency.get("duration_min", 0)
        em_end = arrival + em_duration
        em_task_id = emergency.get("id", emergency.get("task_id", "emergency"))
        api_call({
            "cmd": "insert", "calendar_id": calendar_id,
            "event": {
                "task_id": em_task_id, "title": emergency["title"],
                "start": format_time(arrival), "end": format_time(em_end),
                "status": "emergency",
            },
        })
        emergency_ids.add(em_task_id)

        # Completed = preserved normal tasks (not emergencies)
        completed_ids = set()
        for evt in preserved:
            tid = evt.get("task_id")
            if tid and tid not in emergency_ids:
                completed_ids.add(tid)

        # Rebuild remaining plan from emergency end time
        remaining_tasks = [
            (idx, task) for idx, task in enumerate(tasks)
            if task["id"] not in completed_ids
        ]
        new_schedule, missed_ids = build_schedule(
            remaining_tasks, config, em_end, completed_ids
        )
        for evt in new_schedule:
            api_call({
                "cmd": "insert", "calendar_id": calendar_id,
                "event": {
                    "task_id": evt["task_id"], "title": evt["title"],
                    "start": evt["start"], "end": evt["end"],
                    "status": "rescheduled",
                },
            })
            ever_rescheduled.add(evt["task_id"])

    # Assemble final output from calendar state
    resp = api_call({"cmd": "list", "calendar_id": calendar_id})
    final_events = resp.get("events", [])

    def get_status(task_id):
        if task_id in emergency_ids:
            return "emergency"
        if task_id in ever_rescheduled:
            return "rescheduled"
        return "scheduled"

    schedule_out = []
    for evt in final_events:
        tid = evt.get("task_id", "")
        schedule_out.append({
            "task_id": tid, "title": evt.get("title", ""),
            "start": evt.get("start", ""), "end": evt.get("end", ""),
            "status": evt.get("status", get_status(tid)),
        })
    schedule_out.sort(key=lambda e: parse_time(e["start"]))

    # Completion summary: normal tasks only, SORTED alphabetically
    completed = sorted(
        e["task_id"] for e in schedule_out
        if e["status"] in ("scheduled", "rescheduled")
    )
    all_normal_ids = [t["id"] for t in tasks]
    missed = sorted(tid for tid in all_normal_ids if tid not in set(completed))

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

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    with open(HISTORY_FILE, "w") as f:
        for entry in history_log:
            f.write(json.dumps(entry) + "\n")
    print(f"Schedule: {len(completed)} completed, {len(missed)} missed")
    print(f"  Completed: {completed}")
    print(f"  Missed:    {missed}")

if __name__ == "__main__":
    main()
