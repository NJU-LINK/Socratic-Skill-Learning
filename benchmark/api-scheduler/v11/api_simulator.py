#!/usr/bin/env python3
"""Google Calendar API Simulator.

Reads JSON commands from stdin (one per line) and outputs JSON responses.

Commands: clear, insert, list, delete
State is persisted across invocations via a temp file.
"""
import json, sys, os, random

STATE_FILE = os.environ.get("SIM_STATE_FILE", "/tmp/calendar_state.json")
CALENDAR_ID_ENV = "CALENDAR_ID"

def load():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"events": {}, "next_id": 0, "cleared": False}

def save(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def ok(data=None):
    r = {"status": "ok"}
    if data:
        r.update(data)
    return r

def err(msg):
    return {"status": "error", "message": str(msg)}

SIM_CONFIG = {}

def get_config(key, default=None):
    return SIM_CONFIG.get(key, default)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        cmd = json.loads(line)
    except json.JSONDecodeError as e:
        print(json.dumps(err(f"Invalid JSON: {e}")))
        sys.stdout.flush()
        continue

    action = cmd.get("cmd", "")
    cid = cmd.get("calendar_id", os.environ.get(CALENDAR_ID_ENV, "default"))

    # Rate limiting simulation
    rate_limit = get_config("rate_limit", 0)
    if rate_limit > 0 and random.random() < rate_limit:
        print(json.dumps(err("Rate limit exceeded. Try again later.")))
        sys.stdout.flush()
        continue

    # Error injection
    error_rate = get_config("error_rate", 0)
    if error_rate > 0 and random.random() < error_rate:
        print(json.dumps(err("Internal server error")))
        sys.stdout.flush()
        continue

    state = load()

    if action == "clear":
        state = {"events": {}, "next_id": 0, "cleared": True}
        save(state)
        print(json.dumps(ok({"message": f"Calendar {cid} cleared"})))

    elif action == "insert":
        evt = cmd.get("event", {})
        if not evt.get("title"):
            print(json.dumps(err("Event must have a title")))
            sys.stdout.flush()
            continue
        eid = f"evt_{state['next_id']}"
        state["next_id"] += 1
        evt["id"] = eid
        state.setdefault("events", {})[eid] = evt
        save(state)
        print(json.dumps(ok({"event_id": eid})))

    elif action == "delete":
        eid = cmd.get("event_id")
        if not eid:
            print(json.dumps(err("event_id required")))
            sys.stdout.flush()
            continue
        if eid in state.get("events", {}):
            del state["events"][eid]
            save(state)
            print(json.dumps(ok({"deleted": eid})))
        else:
            print(json.dumps(err(f"Event {eid} not found")))

    elif action == "list":
        events = list(state.get("events", {}).values())
        print(json.dumps(ok({"events": events, "count": len(events)})))

    elif action == "get":
        eid = cmd.get("event_id")
        evt = state.get("events", {}).get(eid)
        if evt:
            print(json.dumps(ok({"event": evt})))
        else:
            print(json.dumps(err(f"Event {eid} not found")))

    else:
        print(json.dumps(err(f"Unknown command: {action}")))

    sys.stdout.flush()
