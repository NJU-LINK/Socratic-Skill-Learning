#!/usr/bin/env python3
"""
General API Scheduler Solver

This script implements the complete scheduling algorithm for the api-scheduler
skill family. It handles:
- All three priority methods (urgency, eisenhower, weighted)
- Dependency DAGs with missed-task cascading
- Emergency replanning with partial-progress invalidation
- Transient API errors with retry
- Optional batch insertion (auto-detected)

Usage:
    python3 solve.py

Input:  /app/tasks.json
Output: /app/output.json, /app/history.jsonl
"""
import json
import subprocess
import sys
import os

# ─── Time helpers ─────────────────────────────────────────────────────────

def time_to_min(t):
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = map(int, t.split(':'))
    return h * 60 + m

def min_to_time(m):
    """Convert minutes since midnight to 'HH:MM'."""
    return f"{m // 60:02d}:{m % 60:02d}"

# ─── Priority scoring ─────────────────────────────────────────────────────

def compute_score(task, method):
    """
    Compute priority score based on the method specified in config.
    
    Methods:
      urgency:    score = urgency
      eisenhower: score = urgency * importance
      weighted:   score = 0.6*u + 0.4*i  (no team_priority)
                  score = 0.5*u + 0.3*i + 0.2*t  (with team_priority)
    """
    u = task.get('urgency', 0)
    i = task.get('importance', 0)
    t = task.get('team_priority', None)
    
    if method == 'urgency':
        return u
    elif method == 'eisenhower':
        return u * i
    elif method == 'weighted':
        if t is not None:
            return 0.5 * u + 0.3 * i + 0.2 * t
        else:
            return 0.6 * u + 0.4 * i
    else:
        return u

def sort_key_for_task(task, method, task_order):
    """
    Sort key for priority ordering:
      1. Higher score first (negate for ascending sort)
      2. Earlier deadline first (no deadline = infinity)
      3. Input order in tasks.json
    """
    score = compute_score(task, method)
    deadline = task.get('deadline')
    if deadline:
        dl = time_to_min(deadline)
    else:
        dl = float('inf')
    return (-score, dl, task_order[task['id']])

# ─── API interaction ──────────────────────────────────────────────────────

history = []

def api_call(cmd_dict, max_retries=20):
    """
    Send a command to the simulator, retrying on transient errors.
    Records every attempt (including failures) in history.
    
    Transient errors include: rate limit, try again, transient, internal server.
    """
    cmd_json = json.dumps(cmd_dict)
    for attempt in range(max_retries):
        result = subprocess.run(
            ['python3', '/app/api_simulator.py'],
            input=cmd_json + '\n',
            capture_output=True,
            text=True
        )
        response = json.loads(result.stdout.strip())
        history.append({"request": dict(cmd_dict), "response": response})
        
        if response.get('status') == 'ok':
            return response
        
        # Check if it's a transient error (retryable)
        msg = response.get('message', '')
        transient_keywords = ['rate limit', 'try again', 'transient', 'internal server']
        if any(kw in msg.lower() for kw in transient_keywords):
            continue  # retry
        
        # Non-transient error - return it
        return response
    
    # Exhausted retries
    return response

def detect_batch_support():
    """Check if api_simulator.py supports batch_insert command."""
    try:
        with open('/app/api_simulator.py') as f:
            code = f.read()
        return 'batch_insert' in code
    except:
        return False

# ─── Scheduling engine ────────────────────────────────────────────────────

def build_schedule(tasks, config, task_order, start_time, 
                   already_completed=None, already_scheduled=None):
    """
    Greedy scheduler: repeatedly pick highest-priority task whose
    dependencies are satisfied, schedule if it fits, otherwise mark missed.
    
    Args:
        tasks: list of task dicts
        config: config dict with work_end, priority_method
        task_order: dict mapping task_id -> input order index
        start_time: minutes since midnight to start scheduling
        already_completed: set of task_ids already completed
        already_scheduled: list of schedule events already placed
    
    Returns:
        (schedule_events, completed_ids_set, missed_ids_list, final_time)
    """
    if already_completed is None:
        already_completed = set()
    if already_scheduled is None:
        already_scheduled = []
    
    method = config['priority_method']
    work_end = time_to_min(config['work_end'])
    
    remaining = list(tasks)
    schedule = list(already_scheduled)
    completed = set(already_completed)
    missed = []
    current_time = start_time
    
    while remaining:
        # Sort remaining by priority
        remaining.sort(key=lambda t: sort_key_for_task(t, method, task_order))
        
        # Find highest priority task whose deps are satisfied
        scheduled_ids = [e['task_id'] for e in schedule]
        all_done = completed | set(scheduled_ids)
        
        placed = False
        for task in remaining:
            deps = task.get('depends_on', [])
            if all(d in all_done for d in deps):
                # This task's deps are satisfied
                duration = task['duration_min']
                end_time = current_time + duration
                
                # Check deadline and work_end
                deadline = task.get('deadline')
                fits = True
                if deadline and end_time > time_to_min(deadline):
                    fits = False
                if end_time > work_end:
                    fits = False
                
                if fits:
                    schedule.append({
                        "task_id": task['id'],
                        "title": task['title'],
                        "start": min_to_time(current_time),
                        "end": min_to_time(end_time),
                    })
                    completed.add(task['id'])
                    current_time = end_time
                    remaining.remove(task)
                    placed = True
                    break
                else:
                    # This task doesn't fit - mark missed and cascade
                    missed.append(task['id'])
                    remaining.remove(task)
                    cascade_missed(task['id'], remaining, missed)
                    placed = True
                    break
        
        if not placed:
            # No task had satisfied deps - all remaining are blocked
            for t in remaining:
                missed.append(t['id'])
            break
    
    return schedule, completed, missed, current_time

def cascade_missed(missed_id, remaining, missed_list):
    """
    Remove and mark as missed all tasks that depend on missed_id.
    Recursively cascades to dependents.
    """
    to_remove = []
    for t in remaining:
        if missed_id in t.get('depends_on', []):
            to_remove.append(t)
    for t in to_remove:
        remaining.remove(t)
        missed_list.append(t['id'])
        cascade_missed(t['id'], remaining, missed_list)

# ─── Main solver ──────────────────────────────────────────────────────────

def main():
    # Load tasks
    with open('/app/tasks.json') as f:
        data = json.load(f)
    
    tasks = data['tasks']
    config = data['config']
    emergencies = data.get('emergencies', [])
    calendar_id = config['calendar_id']
    
    work_start = time_to_min(config['work_start'])
    work_end = time_to_min(config['work_end'])
    
    task_order = {t['id']: idx for idx, t in enumerate(tasks)}
    task_map = {t['id']: t for t in tasks}
    
    # Detect batch support
    batch_supported = detect_batch_support()
    
    # Step 1: Clear calendar (must be first mutating call)
    resp = api_call({"cmd": "clear", "calendar_id": calendar_id})
    print(f"Clear: {resp}")
    
    # Step 2: Build initial schedule
    schedule, completed, missed, current_time = build_schedule(
        tasks, config, task_order, work_start
    )
    
    # Step 3: Submit initial plan to API with status="scheduled"
    if batch_supported and schedule:
        events_for_batch = []
        for evt in schedule:
            events_for_batch.append({
                "task_id": evt['task_id'],
                "title": evt['title'],
                "start": evt['start'],
                "end": evt['end'],
                "status": "scheduled"
            })
        resp = api_call({
            "cmd": "batch_insert",
            "calendar_id": calendar_id,
            "events": events_for_batch
        })
        print(f"Batch insert: {resp}")
    else:
        for evt in schedule:
            event = {
                "task_id": evt['task_id'],
                "title": evt['title'],
                "start": evt['start'],
                "end": evt['end'],
                "status": "scheduled"
            }
            resp = api_call({
                "cmd": "insert",
                "calendar_id": calendar_id,
                "event": event
            })
            print(f"Insert {evt['task_id']}: {resp}")
    
    # Step 4: Handle emergencies (in chronological order)
    for emerg in sorted(emergencies, key=lambda e: time_to_min(e['arrival_time'])):
        arrival = time_to_min(emerg['arrival_time'])
        emerg_duration = emerg['duration_min']
        emerg_end = arrival + emerg_duration
        
        # 1. Keep events whose end <= arrival
        kept = []
        interrupted = []
        for evt in schedule:
            evt_end_min = time_to_min(evt['end'])
            if evt_end_min <= arrival:
                kept.append(evt)
            else:
                interrupted.append(evt)
        
        # 2. Delete events with end > arrival from calendar
        list_resp = api_call({"cmd": "list", "calendar_id": calendar_id})
        for api_evt in list_resp.get('events', []):
            evt_end_min = time_to_min(api_evt['end'])
            if evt_end_min > arrival:
                del_resp = api_call({
                    "cmd": "delete",
                    "calendar_id": calendar_id,
                    "event_id": api_evt['id']
                })
                print(f"Delete {api_evt['id']}: {del_resp}")
        
        # 3. Insert emergency event with status="emergency"
        emerg_event = {
            "task_id": emerg['id'],
            "title": emerg['title'],
            "start": emerg['arrival_time'],
            "end": min_to_time(emerg_end),
            "status": "emergency"
        }
        resp = api_call({
            "cmd": "insert",
            "calendar_id": calendar_id,
            "event": emerg_event
        })
        print(f"Insert emergency {emerg['id']}: {resp}")
        
        # Build emergency schedule entry
        emerg_schedule_entry = {
            "task_id": emerg['id'],
            "title": emerg['title'],
            "start": emerg['arrival_time'],
            "end": min_to_time(emerg_end),
            "status": "emergency"
        }
        
        # 4. Determine remaining tasks to reschedule
        completed_before = set(e['task_id'] for e in kept)
        
        # Tasks still needing scheduling = all tasks minus completed minus emergency
        all_task_ids = set(t['id'] for t in tasks)
        already_done = completed_before
        remaining_tasks = [
            task_map[tid] for tid in all_task_ids
            if tid not in already_done and tid != emerg['id']
        ]
        
        # Rebuild schedule from emergency end
        reschedule, new_completed, new_missed, current_time = build_schedule(
            remaining_tasks, config, task_order, emerg_end,
            already_completed=already_done,
            already_scheduled=kept + [emerg_schedule_entry]
        )
        
        # Submit rescheduled events to API with status="rescheduled"
        kept_ids = set(e['task_id'] for e in kept)
        for evt in reschedule:
            if evt['task_id'] not in kept_ids and evt['task_id'] != emerg['id']:
                evt['status'] = 'rescheduled'
                event = {
                    "task_id": evt['task_id'],
                    "title": evt['title'],
                    "start": evt['start'],
                    "end": evt['end'],
                    "status": "rescheduled"
                }
                resp = api_call({
                    "cmd": "insert",
                    "calendar_id": calendar_id,
                    "event": event
                })
                print(f"Insert rescheduled {evt['task_id']}: {resp}")
        
        schedule = reschedule
        completed = new_completed
        missed = new_missed
    
    # Step 5: List final calendar state (required by tests)
    list_resp = api_call({"cmd": "list", "calendar_id": calendar_id})
    print(f"Final list: {list_resp}")
    
    # Step 6: Build output
    # Completed and missed lists must be SORTED alphabetically
    all_completed = sorted(list(completed))
    
    # Missed list
    emerg_ids = set(e['id'] for e in emergencies)
    scheduled_ids = set(e['task_id'] for e in schedule)
    all_missed = sorted([
        t['id'] for t in tasks
        if t['id'] not in scheduled_ids and t['id'] not in emerg_ids
    ])
    
    # Schedule events include status field (matches remote state)
    output_schedule = []
    for evt in schedule:
        output_schedule.append({
            "task_id": evt['task_id'],
            "title": evt['title'],
            "start": evt['start'],
            "end": evt['end'],
            "status": evt.get('status', 'scheduled')
        })
    
    output = {
        "schedule": output_schedule,
        "completion_summary": {
            "completed": all_completed,
            "missed": all_missed,
            "total_tasks": len(tasks),
            "completed_count": len(all_completed),
            "missed_count": len(all_missed)
        }
    }
    
    with open('/app/output.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    # Step 7: Write history
    with open('/app/history.jsonl', 'w') as f:
        for entry in history:
            f.write(json.dumps(entry) + '\n')
    
    print("\n=== Final Schedule ===")
    for evt in output_schedule:
        print(f"  {evt['task_id']}: {evt['start']} - {evt['end']} ({evt['status']})")
    print(f"Completed: {all_completed}")
    print(f"Missed: {all_missed}")

if __name__ == '__main__':
    main()
