---
name: api-scheduler
description: Reusable instructions for api-scheduler tasks.
---

# api-scheduler

[RULE 001] Solve and verify with API state query
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing by querying the remote API state back (e.g., list or get commands) to confirm it matches expectations and recording all such verification queries in the interaction history.

[RULE 002] Output-state consistency and sorting
content: When the task requires the remote API state to exactly match a local output file, include every field that will appear in the output (including derived fields like status) inside the event payload sent to the API so the persisted state mirrors the output, and sort summary lists alphabetically by identifier rather than by processing order.
