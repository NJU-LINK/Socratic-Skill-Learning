# Calendar API simulator and scheduling contract

The simulator reads one JSON command per line from standard input and writes
one JSON response per line. State persists across invocations in the same task
container.

Every request must contain the `calendar_id` from `tasks.json`. Supported basic
commands are:

```json
{"cmd":"clear","calendar_id":"..."}
{"cmd":"insert","calendar_id":"...","event":{"task_id":"A","title":"...","start":"14:00","end":"15:00"}}
{"cmd":"list","calendar_id":"..."}
{"cmd":"get","calendar_id":"...","event_id":"evt_0"}
{"cmd":"delete","calendar_id":"...","event_id":"evt_0"}
```

A successful response has `status: "ok"`. An error response has
`status: "error"` and does not mutate state. Some variants inject transient
errors; retry the same logical operation until it succeeds. Record every
attempt, including errors, in `history.jsonl` as one JSON object:

```json
{"request":{...},"response":{...}}
```

The first successful mutating request must be `clear`. The final simulator
state must exactly match `output.json`.

## Deterministic priority

Let `u`, `i`, and `t` be urgency, importance, and team priority.

- `urgency`: score = `u`
- `eisenhower`: score = `u * i`
- `weighted` without `team_priority`: score = `0.6*u + 0.4*i`
- `weighted` when `team_priority` is present:
  score = `0.5*u + 0.3*i + 0.2*t`

Higher scores come first. Break a tie by the earlier hard deadline; a task
without a deadline sorts after a task with one. Break any remaining tie by
the task's order in `tasks.json`. Distinct task IDs remain distinct even when
their titles are equal.

## Initial plan

Build the initial normal-task plan without reserving time for future
emergencies:

1. Start at `config.work_start`.
2. Repeatedly choose the highest-priority remaining task whose `depends_on`
   tasks have already completed or occur earlier in this same plan.
3. Schedule it at the next free minute only if it finishes by both its hard
   deadline (when present) and `config.work_end`; otherwise mark it missed and
   continue.
4. If a prerequisite is missed, all tasks that still depend on it are missed.

Events are uninterrupted and must contain `task_id`, `title`, `start`, and
`end`. Submit the initial plan to the simulator.

## Emergency replanning

Process emergencies in chronological `arrival_time` order. At each arrival:

1. Preserve calendar events whose `end` is at or before the arrival.
2. Delete every event whose `end` is after the arrival, including an event
   already in progress. Interrupted normal work receives no partial credit
   and returns to the remaining-task pool at full duration.
3. Insert the emergency at exactly its arrival time. It must finish by its
   deadline, when present, and by the work-day end.
4. Starting at the emergency's end, rebuild the remaining normal plan using
   the same dependency and priority rules.

Repeat this process for later emergencies. Final events must be chronological
and non-overlapping.

## Output

Write `/app/output.json`:

```json
{
  "schedule": [
    {
      "task_id": "A",
      "title": "...",
      "start": "14:00",
      "end": "15:00",
      "status": "scheduled"
    }
  ],
  "completion_summary": {
    "completed": ["A"],
    "missed": ["B"],
    "total_tasks": 2,
    "completed_count": 1,
    "missed_count": 1
  }
}
```

Normal events created in the initial plan use `scheduled`; normal events
created after an emergency use `rescheduled`; emergency events use
`emergency`.

Some variants expose additional commands in the public
`api_simulator.py`. When a task requires batch insertion, inspect that file
and submit the initial plan with:

```json
{"cmd":"batch_insert","calendar_id":"...","events":[...]}
```
