# Iteration 3 Changes

## Problem Identified

Iteration 2 failed 3 out of 7 tests. The failures showed:
- Expected: record id=1 should have value=150
- Got: record id=1 has value=100

The WAL contains **UPDATE operations** that modify existing records (changing values from 100→150, 200→250, etc.), not just INSERT operations for new records. The recovery process applied INSERT operations correctly (records 6-11 were added) but failed to apply UPDATE operations (records 1-2 still had old values).

## Root Cause

The skill documentation didn't clearly explain that:
1. WAL frames contain **complete page images** that may include UPDATE operations
2. Each frame **replaces the entire page** with its new version
3. Pages may contain modified versions of existing records, not just new records
4. You must verify that both new records exist AND existing records have updated values

## Changes Made

### 1. Overview Section
Added a "Critical understanding" block that explicitly states:
- WAL frames contain complete page images
- Frames may include INSERT, UPDATE, and DELETE operations
- Each frame replaces the entire page
- All frames must be applied in order

### 2. Strategy A (Direct SQLite Consumption)
Added clarification that SQLite will handle UPDATE operations automatically.

### 3. Strategy B (Manual Frame Application)
Emphasized that:
- Each frame replaces the entire page
- Frames may contain UPDATE operations that modify existing records
- All frames must be applied in order to get the correct final state

### 4. Common Pitfalls
Added pitfall #6:
- WAL contains UPDATE operations, not just INSERTs
- Each frame contains a complete page image that replaces the entire page
- If existing records still have old values, frames were not properly applied
- Always verify both new records and updated values

### 5. Verifying Recovery (New Section)
Added a new section that guides verification:
1. Record count check
2. New records check
3. **Updated records check** (critical for catching this issue)
4. Schema integrity check

Also added common causes if existing records still have old values.

## Expected Impact

These changes should prevent the solver from:
- Only applying INSERT operations while ignoring UPDATE operations
- Failing to verify that existing records have been updated
- Producing output with correct record count but incorrect values

The solver should now:
- Understand that WAL frames contain complete page images
- Apply all frames in order (including those that modify existing pages)
- Verify that both new records exist AND existing records have updated values
