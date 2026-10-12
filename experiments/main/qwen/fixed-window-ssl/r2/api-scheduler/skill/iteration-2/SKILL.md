---
name: api-scheduler
description: >
  Build a priority-based schedule using a stateful calendar API simulator,
  then revise the remote state when emergencies invalidate the plan.
  Handles urgency/eisenhower/weighted scoring, dependency DAGs, hard deadlines,
  work windows, emergency replanning with stateful deletions, transient error
  retries, and batch insertion when required.
---

# API Scheduler Skill

## Problem Summary

You are given a set of normal tasks and zero or more emergencies. You must:
1. Read API documentation (`simulator_intro.md`) and task data (`tasks.json`)
2. Score tasks by the specified priority method
3. Build a dependency-aware greedy schedule within the work window
4. Submit it to a stateful calendar API simulator
5. Process emergencies chronologically: delete interrupted events, insert the emergency, rebuild remaining schedule
6. Log every API request/response to `history.jsonl`
7. Write final schedule and completion summary to `output.json`

## Priority Scoring

Three methods; implement all and select from `config.priority_method`:

| Method | Formula |
|--------|---------|
| `urgency` | score = u |
| `eisenhower` | score = u × i |
| `weighted` (no team_priority) | score = 0.6u + 0.4i |
| `weighted` (with team_priority) | score = 0.5u + 0.3i + 0.2t |

**Tie-breaking** (deterministic, applied in order):
1. Earlier hard deadline wins. A task **without** a deadline sorts **after** a task with one.
2. Earlier position in `tasks.json` input order.

## Scheduling Algorithm

### Initial Plan

This is a **dependency-aware greedy loop**, not a simple sort-then-pack:

```
cursor = work_start
completed = {}
missed = {}
remaining = all normal task IDs

while remaining is not empty:
    satisfied = completed ∪ already_scheduled
    ready = {t ∈ remaining : all depends_on[t] ⊆ satisfied}

    if ready is empty:
        mark all remaining as missed (cascade)
        break

    pick t ∈ ready with highest priority (using sort key above)
    end_time = cursor + duration[t]

    if end_time ≤ hard_deadline[t] (when present) AND end_time ≤ work_end:
        schedule event at [cursor, end_time]
        completed.add(t)
        cursor = end_time
    else:
        mark t as missed
        cascade: transitively mark all tasks depending on t as missed
        remove t from remaining
```

Key invariants:
- Events are non-overlapping and contiguous (no gaps unless waiting for deps)
- A missed task's dependents are ALL cascade-missed
- The initial plan does NOT reserve time for future emergencies

### Emergency Replanning

Process emergencies sorted by `arrival_time`. For each:

1. **Preserve** calendar events whose `end ≤ arrival_time` (already finished)
2. **Delete** every event whose `end > arrival_time` via the API — including in-progress events. No partial credit.
3. **Insert** the emergency at exactly `arrival_time` with its full duration. It must finish by its deadline (if any) and by `work_end`.
4. **Rebuild** remaining normal tasks from the emergency's end time using the same greedy algorithm.
   - `completed_so_far` = normal task IDs from preserved events
   - `remaining` = all_normal_ids − completed_so_far − permanently_missed
   - All rebuilt normal events get status `"rescheduled"`
5. Update `permanently_missed` with any new misses from this rebuild.

Repeat for subsequent emergencies. Each one further fragments the schedule.

## Event Status Labels

| Context | Status value |
|---------|-------------|
| Normal event in initial plan | `"scheduled"` |
| Normal event created after emergency replan | `"rescheduled"` |
| Emergency event | `"emergency"` |

## API Interaction

### Simulator Protocol

The simulator (`api_simulator.py`) reads JSON from stdin, one command per line, writes JSON responses to stdout. State persists at `/tmp/calendar_state.json` across invocations within the same container.

### Required Commands

```json
{"cmd":"clear","calendar_id":"..."}          // MUST be first mutating command
{"cmd":"insert","calendar_id":"...","event":{...}}
{"cmd":"list","calendar_id":"..."}
{"cmd":"get","calendar_id":"...","event_id":"evt_N"}
{"cmd":"delete","calendar_id":"...","event_id":"evt_N"}
```

**Critical**: The event dict sent to `insert` MUST include the `status` field (`"scheduled"`, `"rescheduled"`, or `"emergency"`). The simulator stores all fields you send, and the test compares the remote state (after stripping `id`) with `output.json["schedule"]`. If `status` is missing from the insert event, the remote state won't match output.json and the test will fail.

### Batch Insert (when required)

Inspect `api_simulator.py` source for `"batch_insert"`. If present, use it for the initial plan:
```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```
Some variants **require** batch insertion — tests will check for it.

### Transient Error Handling

Variants with `api_capability: transient-errors` inject random failures. The retry protocol:
- Wrap **each individual API call** in a retry loop (not the entire sequence)
- Retry on **any** `status == "error"` response — the spec guarantees all simulator errors are transient
- Log **every attempt** (including failed ones) to `history.jsonl`
- Retry until success (with a reasonable max, e.g. 50)
- Note: v01 uses messages like "Rate limit exceeded" or "Internal server error", but variants may use different messages. The contract is unconditional retry on any error.

### History Logging

Every request/response pair goes to `/app/history.jsonl` as one JSON object per line:
```json
{"request":{...},"response":{...}}
```
This includes retries, errors, list/get calls — everything.

## Output Format

Write `/app/output.json`:
```json
{
  "schedule": [
    {"task_id":"A","title":"...","start":"14:00","end":"15:00","status":"scheduled"},
    ...
  ],
  "completion_summary": {
    "completed": ["A","B"],
    "missed": ["C","D"],
    "total_tasks": 4,
    "completed_count": 2,
    "missed_count": 2
  }
}
```

The final simulator state (verifiable via `list`) must exactly match `output.json`.

## Implementation Procedure

1. **Read inputs**: `tasks.json`, `simulator_intro.md`, inspect `api_simulator.py`
2. **Configure**: extract calendar_id, work window, priority method, dependencies, deadlines
3. **Start simulator**: launch as subprocess with stdin/stdout piping
4. **Clear**: send `clear` command first
5. **Compute initial schedule**: dependency-aware greedy loop
6. **Submit**: use `batch_insert` if supported, else individual `insert` calls
7. **Process emergencies** (if any): for each in chronological order, delete interrupted events, insert emergency, rebuild remaining
8. **Verify**: call `list` and confirm state matches output
9. **Write outputs**: `output.json` and `history.jsonl`

## Common Pitfalls

- **Not clearing first**: Simulator state persists at `/tmp/calendar_state.json`. Always `clear` before inserting.
- **Sort-then-pack instead of dependency-aware greedy**: Dependencies mean you can't just sort by priority and schedule sequentially. You must check readiness at each step.
- **Forgetting cascade misses**: If task X is missed, ALL tasks that (transitively) depend on X must also be missed.
- **Wrong status labels**: Initial="scheduled", post-emergency normal="rescheduled", emergency="emergency".
- **Status field missing from insert event**: The `status` field must be included in the event dict sent to `insert`, not just in output.json. The simulator stores all fields; the test compares remote state (after stripping `id`) with output.json. If `status` is missing from the insert, the remote state won't match.
- **Partial credit for interrupted events**: None. An event in progress at emergency arrival is fully deleted and the task returns to the pool at full duration.
- **Not logging errors**: Every API attempt, including transient failures, must appear in history.jsonl.
- **Deadline tie-breaking**: A task with NO deadline sorts AFTER a task WITH a deadline (not before).
- **batch_insert detection**: Check the actual `api_simulator.py` source code, don't assume.

## Reference Implementation

See `scripts/scheduler.py` for a complete, parameterized Python implementation that handles all family variants.
