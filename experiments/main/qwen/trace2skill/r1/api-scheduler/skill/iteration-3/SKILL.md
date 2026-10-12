---
name: api-scheduler
description: General starting point for solving tasks in the api-scheduler family.
---

# api-scheduler

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Output and API Requirements

- **Sort Summary Lists**: When constructing the `completion_summary` in `output.json`, always sort the `completed` and `missed` task ID arrays alphabetically. Do not preserve chronological schedule order.
- **API Payload Parity**: When sending mutation commands (e.g., `insert` or `batch_insert`) to the API, ensure the event payload includes all fields required in the final `output.json` schedule (such as the `status` field, e.g., `"scheduled"`, `"rescheduled"`, or `"emergency"`). The simulator persists the exact event dictionary, which must perfectly match the local output. Do not add fields only when constructing the final JSON.