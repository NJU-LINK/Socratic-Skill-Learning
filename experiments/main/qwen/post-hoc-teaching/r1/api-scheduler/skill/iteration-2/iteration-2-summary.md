# Iteration 2 Summary

## Test Results from Iteration 1
- **Passed**: 9/11 tests
- **Failed**: 2 tests

## Failure Analysis

### Failure 1: test_final_calendar_state_matches_output
**Error**: 
```
assert remote == output["schedule"]
At index 0 diff: {'task_id': 'A', 'title': 'Review Q3 Report', 'start': '14:00', 'end': '15:00'} != {'task_id': 'A', 'title': 'Review Q3 Report', 'start': '14:00', 'end': '15:00', 'status': 'scheduled'}
```

**Root Cause**: 
The test compares the remote calendar state (after stripping IDs) directly to `output["schedule"]`. The remote state events have only 4 fields: `task_id`, `title`, `start`, `end`. But our output schedule entries included a 5th field: `status`. This caused the comparison to fail.

**Fix**: 
- Removed `status` field from all schedule entries in output.json
- Removed `status_label` parameter from `build_schedule()` function
- Removed status tracking from emergency events
- Updated output format documentation to specify exactly 4 fields per schedule entry

### Failure 2: test_history_has_valid_calendar_requests_and_responses
**Error**:
```
assert successful(entries, "list")
AssertionError: assert []
```

**Root Cause**:
The test requires at least one successful `list` command in history.jsonl. Our implementation never called the `list` API endpoint for the no-emergencies v01 case.

**Fix**:
- Added mandatory final `list` command after all scheduling operations
- This serves both as a test requirement and as a verification step
- Updated verification checklist to include this requirement

## Changes Made to SKILL.md

### 1. Output Format (Section 6)
**Before**:
```json
{
  "schedule": [
    {
      "task_id": "A",
      "title": "Review Q3 Report",
      "start": "14:00",
      "end": "15:00",
      "status": "scheduled"
    }
  ]
}
```

**After**:
```json
{
  "schedule": [
    {
      "task_id": "A",
      "title": "Review Q3 Report",
      "start": "14:00",
      "end": "15:00"
    }
  ]
}
```

Added explicit warning:
> **IMPORTANT — schedule format**: Each entry in `schedule` must contain EXACTLY four fields: `task_id`, `title`, `start`, `end`. Do NOT include a `status` field.

### 2. Verification Checklist
Added new requirement:
- [ ] `/app/history.jsonl` contains at least one successful `list` command

Updated existing requirements:
- [ ] Schedule entries have EXACTLY four fields: `task_id`, `title`, `start`, `end` (no `status`)
- [ ] Schedule entries are sorted by `(start, task_id)`

### 3. Reference Implementation
**Changes**:
1. Removed `status_label` parameter from `build_schedule()` function signature
2. Removed `"status": status_label` from event construction
3. Removed `"status": "emergency"` from emergency event construction
4. Added final list command: `final_list_resp = api_call_with_retry({"cmd": "list", "calendar_id": calendar_id})`
5. Updated sort key from `lambda e: to_minutes(e["start"])` to `lambda e: (e["start"], e["task_id"])`
6. Simplified completed/missed calculation to not filter by status

### 4. Emergency Handling (Section 5)
Removed status-related instructions:
- ~~Status: "emergency"~~
- ~~Events created during replanning get status "rescheduled"~~

## Verification

Tested the updated implementation against v01:
- ✓ Schedule has 5 events with correct format (no status field)
- ✓ History contains 7 entries including 1 successful list command
- ✓ Remote state matches output schedule exactly
- ✓ All 5 tasks completed, 0 missed

## Key Insights

1. **Test contracts override documentation**: The simulator_intro.md documentation showed `status` in the output format, but the actual test compares against remote state which doesn't have status. Always verify against test behavior, not just documentation.

2. **Implicit requirements**: The test requires a `list` command in history, but this wasn't explicitly stated in the task description. This is a common pattern in API interaction tasks - verification commands are expected.

3. **Sorting matters**: The test sorts remote events by `(start, task_id)`, so output must be sorted the same way to match.

## Generalization

These fixes improve generalization because:
- The output format now matches the actual API contract (remote state), not just the documentation
- The list command requirement applies to all variants, not just v01
- The sorting requirement is universal across all test cases
- Removing status simplifies the implementation and reduces potential for errors
