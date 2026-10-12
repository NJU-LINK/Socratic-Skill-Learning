#!/bin/bash
set -euo pipefail
exec python3 <<'PY'
import copy
import json
import subprocess


def minute(value):
    hour, minutes = value.split(":")
    return int(hour) * 60 + int(minutes)


def clock(value):
    return f"{value // 60:02d}:{value % 60:02d}"


with open("/app/tasks.json", encoding="utf-8") as handle:
    data = json.load(handle)

normal_tasks = []
for index, raw in enumerate(data["tasks"]):
    task = copy.deepcopy(raw)
    task["_index"] = index
    normal_tasks.append(task)

emergencies = []
for index, raw in enumerate(data.get("emergencies", [])):
    task = copy.deepcopy(raw)
    task["_index"] = index
    emergencies.append(task)

config = data["config"]
method = config["priority_method"]
calendar_id = config["calendar_id"]
work_start = minute(config["work_start"])
work_end = minute(config["work_end"])
history = []


def score(task):
    urgency = int(task.get("urgency", 0))
    importance = int(task.get("importance", 0))
    if method == "urgency":
        return urgency
    if method == "eisenhower":
        return urgency * importance
    if "team_priority" in task:
        return 5 * urgency + 3 * importance + 2 * int(task["team_priority"])
    return 6 * urgency + 4 * importance


def priority_key(task):
    deadline = minute(task["deadline"]) if task.get("deadline") else 10**9
    return (-score(task), deadline, task["_index"])


def event(task, start, status):
    return {
        "task_id": task["id"],
        "title": task["title"],
        "start": clock(start),
        "end": clock(start + int(task["duration_min"])),
        "status": status,
    }


def normal_plan(tasks, start, already_completed, status):
    remaining = list(tasks)
    completed = set(already_completed)
    planned = []
    current = start
    while remaining:
        eligible = [
            task for task in remaining
            if set(task.get("depends_on", [])) <= completed
        ]
        if not eligible:
            break
        task = min(eligible, key=priority_key)
        remaining.remove(task)
        finish = current + int(task["duration_min"])
        deadline = minute(task["deadline"]) if task.get("deadline") else work_end
        if finish > work_end or finish > deadline:
            continue
        planned.append(event(task, current, status))
        completed.add(task["id"])
        current = finish
    return planned


def api(command):
    request = copy.deepcopy(command)
    request["calendar_id"] = calendar_id
    for _ in range(50):
        proc = subprocess.run(
            ["python3", "/app/api_simulator.py"],
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if proc.returncode != 0 or len(lines) != 1:
            raise RuntimeError(f"simulator failure: {proc.stdout}\n{proc.stderr}")
        response = json.loads(lines[0])
        history.append({"request": copy.deepcopy(request), "response": response})
        if response.get("status") == "ok":
            return response
    raise RuntimeError(f"operation did not succeed after retries: {request}")


api({"cmd": "clear"})
current_events = normal_plan(normal_tasks, work_start, set(), "scheduled")
simulator_source = open("/app/api_simulator.py", encoding="utf-8").read()
batch_supported = 'action == "batch_insert"' in simulator_source
if batch_supported:
    if current_events:
        api({"cmd": "batch_insert", "events": current_events})
else:
    for item in current_events:
        api({"cmd": "insert", "event": item})

normal_by_id = {task["id"]: task for task in normal_tasks}
for emergency in sorted(emergencies, key=lambda item: (minute(item["arrival_time"]), item["_index"])):
    arrival = minute(emergency["arrival_time"])
    state_events = api({"cmd": "list"}).get("events", [])
    state_by_task = {item.get("task_id"): item for item in state_events}
    removed = [item for item in current_events if minute(item["end"]) > arrival]
    for item in removed:
        remote = state_by_task.get(item["task_id"])
        if not remote or not remote.get("id"):
            raise RuntimeError(f"missing calendar event for {item['task_id']}")
        api({"cmd": "delete", "event_id": remote["id"]})

    preserved = [item for item in current_events if minute(item["end"]) <= arrival]
    completed_normal = {
        item["task_id"] for item in preserved if item["task_id"] in normal_by_id
    }
    deadline = minute(emergency["deadline"]) if emergency.get("deadline") else work_end
    finish = arrival + int(emergency["duration_min"])
    if finish <= work_end and finish <= deadline:
        emergency_event = event(emergency, arrival, "emergency")
        api({"cmd": "insert", "event": emergency_event})
        preserved.append(emergency_event)
        restart_at = finish
    else:
        restart_at = arrival

    remaining = [
        task for task in normal_tasks if task["id"] not in completed_normal
    ]
    rebuilt = normal_plan(remaining, restart_at, completed_normal, "rescheduled")
    for item in rebuilt:
        api({"cmd": "insert", "event": item})
    current_events = sorted(preserved + rebuilt, key=lambda item: (item["start"], item["task_id"]))

api({"cmd": "list"})
completed = sorted(item["task_id"] for item in current_events)
all_ids = sorted(
    [task["id"] for task in normal_tasks] + [task["id"] for task in emergencies]
)
missed = sorted(set(all_ids) - set(completed))
output = {
    "schedule": current_events,
    "completion_summary": {
        "completed": completed,
        "missed": missed,
        "total_tasks": len(all_ids),
        "completed_count": len(completed),
        "missed_count": len(missed),
    },
}
with open("/app/output.json", "w", encoding="utf-8") as handle:
    json.dump(output, handle, indent=2)
with open("/app/history.jsonl", "w", encoding="utf-8") as handle:
    for entry in history:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
PY
