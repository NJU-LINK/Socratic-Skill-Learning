# Iteration 2 Summary

## Critical Bug Fixed

### Issue: Project Members Should Be IDs, Not Names

**Root Cause**: The SKILL.md incorrectly instructed to resolve employee IDs to employee names in the project `members` array.

**Evidence from Test Failures**:
1. `test_project_members_remain_within_their_owning_department` failed because:
   - Test collects employee IDs: `{employee["id"] for employee in department["employees"]}`
   - Test checks: `set(project["members"]).issubset(employee_ids)`
   - Our output had names like `"Cristiano Ronaldo"` but test expected IDs like `"D001-E001"`

2. `test_departments_employees_and_projects_match_public_csv_inputs` failed because:
   - Exact equality check on department structure
   - Project members were names instead of IDs

**Fix Applied**:
- Updated SKILL.md to clearly state that `members` array contains employee **IDs**, not names
- Updated `generate.py` to keep member IDs as-is from CSV (no name resolution)
- Removed unused `emp_by_id` lookup structure
- Added evidence-based explanation: column is named `member_ids` and tests verify ID subset relationship

**Key Insight**: When schema is ambiguous (just says "array of strings"), use:
1. Column naming conventions (`member_ids` → should be IDs)
2. Test expectations (subset check against employee IDs)
3. Data flow logic (CSV already contains the correct values)

## Files Modified

1. `SKILL.md`:
   - Line 7: Description updated to say "employee IDs via semicolon parsing"
   - Line 54: Schema documentation updated to say "employee **IDs**, not names"
   - Lines 132-140: Step 4 updated to keep IDs as-is
   - Line 216: Entity relationship table updated
   - Line 217: Cross-department reference handling clarified
   - Line 301: Common pitfall #1 updated with test evidence

2. `scripts/generate.py`:
   - Removed `emp_by_id` lookup (no longer needed)
   - Simplified project member handling to just parse semicolon-delimited IDs
   - No name resolution logic

## Test Results

All checks now pass:
- ✓ Schema validation
- ✓ Project members are employee IDs (subset of department employee IDs)
- ✓ Department structure matches CSV inputs
- ✓ Statistics are correct
- ✓ Metadata is well-formed

## Verification Command

```bash
python3 /skill/scripts/generate.py
python3 -c "
import json, jsonschema
with open('/app/schema.json') as f: schema = json.load(f)
with open('/app/organization.json') as f: data = json.load(f)
jsonschema.validate(data, schema)
for dept in data['organization']['departments']:
    emp_ids = {e['id'] for e in dept['employees']}
    for proj in dept['projects']:
        assert set(proj['members']).issubset(emp_ids)
print('✓ All checks passed')
"
```
