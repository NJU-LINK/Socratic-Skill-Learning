---
name: api-scheduler
description: General starting point for solving tasks in the api-scheduler family.
---

# api-scheduler

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Output and API Synchronization

- **Sort summary lists**: Always sort the `completed` and `missed` arrays in the `completion_summary` alphabetically by task ID before writing to `output.json`. Do not rely on chronological or insertion order.
- **Synchronize API payloads**: Include all fields required in the final `output.json` (such as `status`, e.g., `"scheduled"`, `"rescheduled"`, or `"emergency"`) directly in the `event` payload sent to the calendar API's `insert` commands. The simulator persists exactly the JSON payload it receives, so the API request must perfectly mirror the desired final state.