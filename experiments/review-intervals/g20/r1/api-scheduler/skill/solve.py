#!/usr/bin/env python3
"""
Reference implementation for the api-scheduler skill.
"""
import json
import subprocess
import sys
import os

def time_to_min(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def min_to_time(m):
    return f"{m // 60:02d}:{m % 60:02d}"

def compute_score(task, method):
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
    else:
        raise ValueError(f"Unknown priority method: {method}")

def sort_key(task, method, task_order_map):
    score = compute_score(task, method)
    deadline = task.get("deadline", None)
    if deadline:
        dl = time_to_min(deadline)
        has_deadline = 0
    else:
        dl = 99999
        has_deadline = 1
    return (-score, has_deadline, dl, task_order_map[task["id"]])

def build_schedule(tasks, method, work_start, work_end, task_order_map,
                   done_set=None, current_time=None):
    if done_set is None:
        done_set = set()
    if current_time is None:
        current_time = work_start
    
    remaining = list(tasks)
    new_events = []
    missed = []
    cur_time = current_time
    done = set(done_set)
    
    max_iterations = len(remaining) * len(remaining) + 10
    iteration = 0
    
    while remaining and iteration < max_iterations:
        iteration += 1
        remaining.sort(key=lambda t: sort_key(t, method, task_order_map))
        
        placed_or_decided = False
        for task in remaining:
            tid = task["id"]
            dur = task["duration_min"]
            deadline = task.get("deadline", None)
            depends = task.get("depends_on", [])
            
            deps_met = all(d in done for d in depends)
            if not deps_met:
                deps_missed = any(d in missed for d in depends)
                if deps_missed:
                    missed.append(tid)
                    remaining.remove(task)
                    placed_or_decided = True
                    break
                continue
            
            end_time = cur_time + dur
            fits_deadline = (deadline is None) or (end_time <= time_to_min(deadline))
            fits_window = end_time <= work_end
            
            if fits_deadline and fits_window:
                new_events.append({
                    "task_id": tid,
                    "title": task["title"],
                    "start": min_to_time(cur_time),
                    "end": min_to_time(end_time),
                })
                cur_time = end_time
                done.add(tid)
                remaining.remove(task)
                placed_or_decided = True
                break
            else:
                missed.append(tid)
                remaining.remove(task)
                placed_or_decided = True
                break
        
        if not placed_or_decided:
            for task in remaining:
                missed.append(task["id"])
            break
    
    return new_events, missed


class APIClient:
    def __init__(self, calendar_id, simulator_path="/app/api_simulator.py"):
        self.calendar_id = calendar_id
        self.simulator_path = simulator_path
        self.history = []
        self.proc = None
        self.supports_batch = False
    
    def start(self):
        self.proc = subprocess.Popen(
            ["python3", self.simulator_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        try:
            with open(self.simulator_path) as f:
                if "batch_insert" in f.read():
                    self.supports_batch = True
        except:
            pass
    
    def send_raw(self, cmd_dict):
        request_line = json.dumps(cmd_dict) + "\n"
        self.proc.stdin.write(request_line)
        self.proc.stdin.flush()
        response_line = self.proc.stdout.readline()
        response = json.loads(response_line.strip())
        self.history.append({"request": dict(cmd_dict), "response": response})
        return response
    
    def send(self, cmd_dict, max_retries=15):
        cmd_dict["calendar_id"] = self.calendar_id
        for attempt in range(max_retries):
            response = self.send_raw(cmd_dict)
            if response.get("status") == "ok":
                return response
        raise RuntimeError(f"API call failed after {max_retries} attempts")
    
    def clear(self):
        return self.send({"cmd": "clear"})
    
    def insert(self, event):
        return self.send({"cmd": "insert", "event": event})
    
    def batch_insert(self, events):
        return self.send({"cmd": "batch_insert", "events": events})
    
    def list_events(self):
        return self.send({"cmd": "list"})
    
    def delete(self, event_id):
        return self.send({"cmd": "delete", "event_id": event_id})
    
    def stop(self):
        if self.proc:
            try:
                self.proc.stdin.close()
            except:
                pass
            self.proc.wait()
    
    def save_history(self, path="/app/history.jsonl"):
        with open(path, "w") as f:
            for entry in self.history:
                f.write(json.dumps(entry) + "\n")


def main():
    with open("/app/tasks.json") as f:
        data = json.load(f)
    
    tasks = data["tasks"]
    emergencies = data.get("emergencies", [])
    config = data["config"]
    
    calendar_id = config["calendar_id"]
    work_start = time_to_min(config["work_start"])
    work_end = time_to_min(config["work_end"])
    method = config["priority_method"]
    
    task_order_map = {t["id"]: idx for idx, t in enumerate(tasks)}
    task_map = {t["id"]: t for t in tasks}
    
    api = APIClient(calendar_id)
    api.start()
    api.clear()
    
    # Build initial schedule
    initial_events, initial_missed = build_schedule(
        tasks, method, work_start, work_end, task_order_map
    )
    
    # Track status for each event
    all_events = []
    for evt in initial_events:
        evt["status"] = "scheduled"
        all_events.append(evt)
    
    all_missed = list(initial_missed)
    
    # Submit initial plan - INCLUDE status in insert (pass-through store)
    if api.supports_batch and len(initial_events) > 1:
        batch_events = [{
            "task_id": evt["task_id"],
            "title": evt["title"],
            "start": evt["start"],
            "end": evt["end"],
            "status": evt["status"]  # INCLUDE status
        } for evt in initial_events]
        api.batch_insert(batch_events)
    else:
        for evt in initial_events:
            api.insert({
                "task_id": evt["task_id"],
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"],
                "status": evt["status"]  # INCLUDE status
            })
    
    # Handle emergencies
    emergencies_sorted = sorted(emergencies, key=lambda e: time_to_min(e["arrival_time"]))
    
    for emergency in emergencies_sorted:
        arrival = time_to_min(emergency["arrival_time"])
        e_end = arrival + emergency["duration_min"]
        
        preserved = [evt for evt in all_events if time_to_min(evt["end"]) <= arrival]
        
        cal_list = api.list_events()
        for cal_evt in cal_list.get("events", []):
            if time_to_min(cal_evt["end"]) > arrival:
                api.delete(cal_evt["id"])
        
        interrupted = [evt for evt in all_events if time_to_min(evt["end"]) > arrival]
        returned_ids = set(evt["task_id"] for evt in interrupted if evt["task_id"] in task_map)
        
        emergency_event = {
            "task_id": emergency["id"],
            "title": emergency["title"],
            "start": min_to_time(arrival),
            "end": min_to_time(e_end),
            "status": "emergency"
        }
        # INCLUDE status in emergency insert
        api.insert({
            "task_id": emergency["id"],
            "title": emergency["title"],
            "start": min_to_time(arrival),
            "end": min_to_time(e_end),
            "status": "emergency"  # INCLUDE status
        })
        
        available_ids = returned_ids | set(tid for tid in all_missed if tid in task_map)
        available_tasks = [task_map[tid] for tid in available_ids if tid in task_map]
        done_ids = set(evt["task_id"] for evt in preserved) | {emergency["id"]}
        
        new_events, new_missed = build_schedule(
            available_tasks, method, work_start, work_end, task_order_map,
            done_set=done_ids, current_time=e_end
        )
        
        for evt in new_events:
            evt["status"] = "rescheduled"
            # INCLUDE status in rescheduled insert
            api.insert({
                "task_id": evt["task_id"],
                "title": evt["title"],
                "start": evt["start"],
                "end": evt["end"],
                "status": "rescheduled"  # INCLUDE status
            })
        
        all_events = preserved + [emergency_event] + new_events
        all_missed = new_missed
    
    # Build output WITH status field (required by spec and tests)
    final_schedule = sorted([
        {
            "task_id": evt["task_id"],
            "title": evt["title"],
            "start": evt["start"],
            "end": evt["end"],
            "status": evt["status"]
        }
        for evt in all_events
    ], key=lambda e: (time_to_min(e["start"]), e["task_id"]))
    
    # completed and missed must be SORTED alphabetically
    completed_normal = sorted([evt["task_id"] for evt in final_schedule if evt["task_id"] in task_map])
    missed_normal = sorted([tid for tid in all_missed if tid in task_map])
    
    output = {
        "schedule": final_schedule,
        "completion_summary": {
            "completed": completed_normal,
            "missed": missed_normal,
            "total_tasks": len(tasks),
            "completed_count": len(completed_normal),
            "missed_count": len(missed_normal)
        }
    }
    
    with open("/app/output.json", "w") as f:
        json.dump(output, f, indent=2)
    
    api.save_history()
    api.stop()
    
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()
