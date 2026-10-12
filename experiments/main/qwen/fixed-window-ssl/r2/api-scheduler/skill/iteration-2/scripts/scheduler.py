#!/usr/bin/env python3
"""
General API scheduler for the api-scheduler family.
Handles: all 3 priority methods, dependencies, deadlines, work windows,
0+ emergencies with full replanning, transient error retries,
batch_insert when available, full history logging.
"""
import json, subprocess, sys, os

# ─── time helpers ────────────────────────────────────────────────────────────

def time_to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"

# ─── priority scoring ────────────────────────────────────────────────────────

def compute_score(task, method):
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

def priority_sort_key(task, method, input_order):
    """
    Higher score first → negate.
    Earlier deadline first; no-deadline sorts after deadline.
    Earlier input order breaks remaining ties.
    """
    score = compute_score(task, method)
    deadline = task.get("deadline", None)
    if deadline is not None:
        dl_key = (0, time_to_min(deadline))
    else:
        dl_key = (1, float('inf'))
    return (-score, dl_key, input_order)

# ─── dependency-aware greedy scheduler ───────────────────────────────────────

def build_schedule(remaining_task_ids, task_map, cursor, work_end_min, method,
                   already_completed, depends_on_map, input_order):
    """
    Greedy scheduler respecting dependencies, deadlines, and work_end.

    Args:
        remaining_task_ids: set of task IDs still to be scheduled
        task_map: id → task dict
        cursor: current time in minutes
        work_end_min: work end in minutes
        method: priority method string
        already_completed: set of task IDs already completed (deps satisfied)
        depends_on_map: id → list of dependency task IDs
        input_order: id → original index in tasks.json

    Returns:
        (events, newly_completed, newly_missed, final_cursor)
    """
    events = []
    newly_completed = set()
    newly_missed = set()
    remaining = set(remaining_task_ids)
    t = cursor

    while remaining:
        # Find ready tasks: all depends_on in (already_completed ∪ newly_completed)
        satisfied = already_completed | newly_completed
        ready = []
        for tid in remaining:
            deps = depends_on_map.get(tid, [])
            if all(d in satisfied for d in deps):
                ready.append(tid)

        if not ready:
            # No task can proceed — all remaining are blocked → cascade miss
            for tid in remaining:
                newly_missed.add(tid)
            break

        # Pick highest priority among ready
        ready.sort(key=lambda tid: priority_sort_key(task_map[tid], method, input_order[tid]))
        chosen = ready[0]
        task = task_map[chosen]
        dur = task["duration_min"]
        end_t = t + dur

        # Check constraints
        deadline_min = time_to_min(task["deadline"]) if task.get("deadline") else None
        fits = True
        if deadline_min is not None and end_t > deadline_min:
            fits = False
        if end_t > work_end_min:
            fits = False

        if fits:
            events.append({
                "task_id": chosen,
                "title": task["title"],
                "start": min_to_time(t),
                "end": min_to_time(end_t),
            })
            newly_completed.add(chosen)
            t = end_t
        else:
            # This task can't fit → miss it and cascade
            newly_missed.add(chosen)
            _cascade_miss(chosen, remaining, newly_missed, depends_on_map)

        remaining.discard(chosen)

    return events, newly_completed, newly_missed, t


def _cascade_miss(tid, remaining, missed_set, depends_on_map):
    """Transitively mark tasks in `remaining` that depend on `tid` as missed."""
    frontier = [tid]
    while frontier:
        cur = frontier.pop()
        dependents = [r for r in remaining if cur in depends_on_map.get(r, [])]
        for d in dependents:
            missed_set.add(d)
            remaining.discard(d)
            frontier.append(d)

# ─── API client ──────────────────────────────────────────────────────────────

class CalendarAPI:
    def __init__(self, calendar_id, simulator_path, history_path):
        self.calendar_id = calendar_id
        self.simulator_path = simulator_path
        self.history_path = history_path
        self.proc = None
        open(history_path, "w").close()  # clear history

    def start(self):
        self.proc = subprocess.Popen(
            ["python3", self.simulator_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1
        )

    def send(self, cmd, max_retries=50):
        """Send a command; retry on transient errors; log every attempt."""
        cmd["calendar_id"] = self.calendar_id
        for attempt in range(max_retries):
            req_json = json.dumps(cmd)
            self.proc.stdin.write(req_json + "\n")
            self.proc.stdin.flush()
            resp_line = self.proc.stdout.readline().strip()
            if not resp_line:
                raise RuntimeError("Simulator produced no output")
            resp = json.loads(resp_line)
            # Log every attempt
            with open(self.history_path, "a") as f:
                f.write(json.dumps({"request": dict(cmd), "response": resp}) + "\n")
            if resp.get("status") == "ok":
                return resp
            # Per spec: all simulator errors are transient — retry until success.
            # (v01 messages include "Rate limit exceeded", "Internal server error",
            #  but variants may use any message. The contract is unconditional retry.)
            continue
        raise RuntimeError(f"Max retries ({max_retries}) exceeded for: {cmd.get('cmd')}")

    def clear(self):
        return self.send({"cmd": "clear"})

    def insert(self, event):
        return self.send({"cmd": "insert", "event": dict(event)})

    def batch_insert(self, events):
        return self.send({"cmd": "batch_insert", "events": list(events)})

    def list_events(self):
        return self.send({"cmd": "list"})

    def delete(self, event_id):
        return self.send({"cmd": "delete", "event_id": event_id})

    def close(self):
        if self.proc:
            self.proc.stdin.close()
            self.proc.wait()

# ─── main ────────────────────────────────────────────────────────────────────

def main():
    tasks_path = "/app/tasks.json"
    simulator_path = "/app/api_simulator.py"
    history_path = "/app/history.jsonl"
    output_path = "/app/output.json"

    with open(tasks_path) as f:
        data = json.load(f)

    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    calendar_id = config["calendar_id"]
    work_start_min = time_to_min(config["work_start"])
    work_end_min = time_to_min(config["work_end"])
    method = config["priority_method"]

    task_map = {t["id"]: t for t in tasks}
    input_order = {t["id"]: idx for idx, t in enumerate(tasks)}
    depends_on_map = {t["id"]: t.get("depends_on", []) for t in tasks}
    all_normal_ids = set(t["id"] for t in tasks)

    # Detect batch_insert support
    with open(simulator_path) as f:
        sim_code = f.read()
    supports_batch = "batch_insert" in sim_code

    # Start API
    api = CalendarAPI(calendar_id, simulator_path, history_path)
    api.start()
    api.clear()  # MUST be first mutating command

    # ─── Initial plan ────────────────────────────────────────────────────────
    events, completed, missed, cursor = build_schedule(
        all_normal_ids, task_map, work_start_min, work_end_min, method,
        set(), depends_on_map, input_order
    )
    # Include status in the event sent to simulator (not just output.json)
    # so remote state matches output after id-stripping
    for e in events:
        e["status"] = "scheduled"

    # Submit initial plan
    if supports_batch and events:
        api.batch_insert(events)
    else:
        for e in events:
            api.insert(e)

    # Track global state
    permanently_missed = set(missed)

    # ─── Emergency replanning ────────────────────────────────────────────────
    emergencies_sorted = sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"]))

    for emerg in emergencies_sorted:
        arrival_min = time_to_min(emerg["arrival_time"])

        # Fetch current calendar state
        resp = api.list_events()
        current_events = resp.get("events", [])

        # Partition: keep events ending ≤ arrival, delete the rest
        kept_events = []
        completed_now = set()
        for evt in current_events:
            if time_to_min(evt["end"]) <= arrival_min:
                kept_events.append(evt)
                # Only count normal tasks as completed (not previous emergencies)
                if evt["task_id"] in all_normal_ids:
                    completed_now.add(evt["task_id"])

        # Delete interrupted events
        for evt in current_events:
            if time_to_min(evt["end"]) > arrival_min:
                api.delete(evt["id"])

        # Insert emergency at arrival_time
        emerg_dur = emerg["duration_min"]
        emerg_end_min = arrival_min + emerg_dur
        emerg_event = {
            "task_id": emerg["id"],
            "title": emerg["title"],
            "start": min_to_time(arrival_min),
            "end": min_to_time(emerg_end_min),
            "status": "emergency"
        }
        api.insert(emerg_event)

        # Rebuild remaining normal plan from emergency's end
        remaining = all_normal_ids - completed_now - permanently_missed
        new_events, new_completed, new_missed, cursor = build_schedule(
            remaining, task_map, emerg_end_min, work_end_min, method,
            completed_now, depends_on_map, input_order
        )
        for e in new_events:
            e["status"] = "rescheduled"
            api.insert(e)

        permanently_missed |= new_missed

    # ─── Build output ────────────────────────────────────────────────────────
    resp = api.list_events()
    final_events = sorted(resp.get("events", []), key=lambda e: time_to_min(e["start"]))

    schedule = []
    completed_final = set()
    for evt in final_events:
        tid = evt["task_id"]
        if tid in all_normal_ids or tid in {e["id"] for e in emergencies}:
            schedule.append({
                "task_id": tid,
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"],
                "status": evt.get("status", "scheduled")
            })
            if tid in all_normal_ids:
                completed_final.add(tid)

    missed_final = sorted(all_normal_ids - completed_final, key=lambda tid: input_order[tid])
    completed_sorted = sorted(completed_final, key=lambda tid: input_order[tid])

    output = {
        "schedule": schedule,
        "completion_summary": {
            "completed": completed_sorted,
            "missed": missed_final,
            "total_tasks": len(all_normal_ids),
            "completed_count": len(completed_sorted),
            "missed_count": len(missed_final)
        }
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    api.close()
    print(f"Done. {len(completed_sorted)} completed, {len(missed_final)} missed.")

if __name__ == "__main__":
    main()
