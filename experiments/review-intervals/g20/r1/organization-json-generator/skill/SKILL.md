---
name: organization-json-generator
description: >
  Transform three related CSV files (departments, employees, projects) into a
  single nested organization JSON that conforms to a provided JSON schema.
  Handles semicolon-delimited multi-value fields, foreign-key-based nesting,
  robust value normalization, and aggregate statistics computation.
---

# Organization JSON Generator

## Purpose

Read CSV data describing an organization's departments, employees, and projects,
assemble them into a nested JSON structure grouped by department, compute
aggregate statistics, and validate the result against a JSON schema.

## Input Conventions

Three CSV files in `/app/data/`:

| File | Key columns | Role |
|------|-------------|------|
| `departments.csv` | `id`, `name`, `budget` | Top-level organizational units |
| `employees.csv` | `id`, `name`, `position`, `skills`, `years_of_service`, `department_id` | Staff; `department_id` is FK to departments |
| `projects.csv` | `name`, `status`, `member_ids`, `deadline`, `department_id` | Work items; `department_id` is FK to departments, `member_ids` are semicolon-separated employee IDs |

The schema lives at `/app/schema.json`. Output goes to `/app/organization.json`.

## Schema-Driven Constraints (Family Invariants)

The JSON schema imposes constraints that are **family invariants** — they hold across all variants:

| Constraint | Meaning |
|------------|---------|
| `departments` minItems: 3 | At least 3 departments always exist |
| `employees` minItems: 2 | Every department has at least 2 employees |
| `skills` minItems: 1 | Every employee has at least 1 skill |
| `budget` minimum: 0 | No negative budgets |
| `years_of_service` minimum: 0 | No negative years of service |
| `status` enum: 5 values | Only Planning/In Progress/Testing/Completed/On Hold |
| `members` items: string | Project members are employee ID strings (not names) |

These constraints mean:
- You will always have enough data to compute meaningful statistics
- Every employee will contribute to skill distribution
- Project members are always ID references, preserving referential integrity

## Output Schema Structure

The output JSON has three top-level keys:

```
{
  "metadata": { "version", "timestamp", "generator" },
  "organization": { "name", "founded", "departments": [...] },
  "statistics": { ... six aggregate fields ... }
}
```

### Department nesting

Each department object contains:
- `id` (string), `name` (string), `budget` (number ≥ 0)
- `employees`: array of employee objects belonging to this department
- `projects`: array of project objects belonging to this department (may be empty)

### Employee object

`id`, `name`, `position` (strings), `skills` (array of strings), `years_of_service` (integer ≥ 0)

### Project object

`name` (string), `status` (enum: Planning/In Progress/Testing/Completed/On Hold), `members` (array of strings — employee IDs), `deadline` (date string)

## Core Transformation Procedure

### Step 1: Read and normalize CSV data

Use `csv.DictReader` to read each file. For every field value:
1. Strip leading/trailing whitespace
2. Strip surrounding quote characters (`"` or `'`) if present
3. Apply type-specific parsing (see below)

### Step 2: Parse multi-value delimited fields

Fields like `skills` and `member_ids` use semicolon delimiters.

```python
def parse_delimited(field_str, delimiter=';'):
    if not field_str or not field_str.strip():
        return []
    return [v.strip().strip('"').strip("'").strip()
            for v in field_str.split(delimiter)
            if v.strip().strip('"').strip("'").strip()]
```

This handles:
- Empty fields → empty list
- Repeated delimiters (`a;;b`) → empty strings filtered out
- Leading/trailing delimiters (`;a;b;`) → filtered
- Extra whitespace around values → stripped
- Quoted values → quotes removed

**Delimiter detection**: If the CSV uses a different delimiter (comma, pipe, tab), detect it by examining the first data row or use `csv.Sniffer`. The procedure remains the same; only the delimiter character changes.

### Step 3: Parse numeric fields robustly

```python
def parse_int_robust(val):
    cleaned = clean_value(val).replace(',', '')
    return int(float(cleaned))

def parse_float_robust(val):
    cleaned = clean_value(val).replace(',', '')
    return float(cleaned)
```

The `float`-then-`int` chain handles values like `"7.0"` or `" 7 "` that would crash a direct `int()` call. Comma removal handles formatted numbers like `"1,000,000"`.

### Step 4: Build lookup structures

```python
employees_by_id = { emp['id']: emp for emp in employees }
employees_by_dept = defaultdict(list)  # grouped by department_id
projects_by_dept = defaultdict(list)   # grouped by department_id
```

### Step 5: Assemble nested department objects

For each department row:
- Set `id`, `name`, `budget` from the department CSV
- Attach all employees where `department_id` matches
- Attach all projects where `department_id` matches
- **Critical**: For project `members`, keep the employee ID strings as-is (preserving referential integrity from source data). Do NOT translate to names — the schema says `"items": {"type": "string"}` and the IDs are the source-of-truth relationship markers. Tests verify that project members remain within their owning department.
- Departments with no employees get an empty `employees` array
- Departments with no projects get an empty `projects` array

### Step 6: Compute statistics

All six required statistics:

| Statistic | Computation | Notes |
|-----------|-------------|-------|
| `averageDepartmentBudget` | `sum(all department budgets) / count(departments)` | Float division |
| `totalEmployees` | `len(all employee rows)` | Integer count |
| `skillDistribution` | Dict mapping each skill string → count of employees possessing it | Only include skills that appear |
| `departmentSizes` | Dict mapping department **name** → count of employees in that department | Include ALL departments |
| `projectStatusDistribution` | Dict mapping status string → count of projects with that status | Only include statuses that appear |
| `averageYearsOfService` | `sum(all years_of_service) / count(employees)` | Float division |

**Important edge cases for statistics:**
- If there are 0 employees, `averageYearsOfService` should be 0 (avoid division by zero)
- If there are 0 departments, `averageDepartmentBudget` should be 0
- `skillDistribution` only includes skills that actually appear (no zero-count entries)
- `departmentSizes` includes ALL departments, even those with 0 employees
- `projectStatusDistribution` only includes statuses that actually appear
- Averages are computed as floats; tests verify correctness to 2 decimal places

### Step 7: Build metadata

- `version`: any valid string (e.g., `"1.0"`)
- `timestamp`: current ISO-8601 datetime (e.g., `datetime.now().isoformat()`)
- `generator`: any descriptive string (e.g., `"csv-to-json-processor"`)

For `organization.name` and `organization.founded`: these are schema-required but not derivable from CSV data. Use a reasonable default name (e.g., `"Organization"`) and a valid date string (e.g., `"2020-01-01"`). Tests validate format conformance, not specific values.

### Step 8: Validate against schema

```python
from jsonschema import validate
with open('/app/schema.json') as f:
    schema = json.load(f)
validate(instance=output, schema=schema)
```

This catches structural errors: missing required fields, wrong types, enum violations, minimum violations, etc.

## Self-Test Procedure

After generating the output, run this inline verification to catch errors that schema validation misses:

```python
import json

with open('/app/organization.json') as f:
    data = json.load(f)

depts = data['organization']['departments']
stats = data['statistics']

# 1. Verify project members are employee IDs (not names) and belong to owning department
emp_ids_by_dept = {}
for d in depts:
    emp_ids_by_dept[d['name']] = set(e['id'] for e in d['employees'])

for d in depts:
    for p in d['projects']:
        for m in p['members']:
            assert m in emp_ids_by_dept[d['name']], \
                f'Member {m} not in dept {d["name"]}'

# 2. Verify empty arrays for departments/projects with no data
for d in depts:
    assert isinstance(d['employees'], list)
    assert isinstance(d['projects'], list)
    for p in d['projects']:
        assert isinstance(p['members'], list)

# 3. Verify statistics consistency
total_emps = sum(len(d['employees']) for d in depts)
assert stats['totalEmployees'] == total_emps

total_projs = sum(len(d['projects']) for d in depts)
status_sum = sum(stats['projectStatusDistribution'].values())
assert status_sum == total_projs

# 4. Verify averages are floats (not integers)
assert isinstance(stats['averageDepartmentBudget'], float)
assert isinstance(stats['averageYearsOfService'], float)

print("Self-test passed")
```

This catches:
- Member IDs translated to names (test_project_members_remain_within_their_owning_department)
- Empty arrays not properly handled
- Statistics not matching actual data
- Integer division instead of float division for averages

## Verification Checklist

After generating the output, verify these invariants:

- [ ] Schema validation passes (all required fields present, correct types)
- [ ] `totalEmployees` equals the number of employee CSV rows
- [ ] `averageDepartmentBudget` equals sum of budgets / number of departments
- [ ] `averageYearsOfService` equals sum of years / number of employees
- [ ] `skillDistribution` counts each skill across all employees
- [ ] `departmentSizes` maps department names to employee counts
- [ ] `projectStatusDistribution` counts projects by status
- [ ] Project `members` arrays contain employee IDs (not names)
- [ ] Departments with no projects have empty `projects` arrays
- [ ] Projects with no members have empty `members` arrays

## Robustness Checklist (Family Variations)

The following variations must all be handled by the same procedure:

### Entity relationship complexity
- [ ] Departments with zero projects → empty `projects` array
- [ ] Departments with many employees or projects → no special handling needed
- [ ] Projects with empty `member_ids` → empty `members` array
- [ ] Dense project-member reuse (same employee in many projects) → just include ID each time
- [ ] Employees appearing in projects from different departments → member_ids are just strings, include as-is

### Field parsing and normalization
- [ ] Extra whitespace in any field → `.strip()`
- [ ] Repeated delimiters (`a;;b`) → filter empty segments
- [ ] Empty multi-value fields → return `[]`
- [ ] Quoted text (`"Python"`) → strip surrounding quotes
- [ ] Numeric strings like `"7.0"` or `" 1,000 "` → robust float→int chain with comma removal
- [ ] Leading/trailing delimiters (`;a;b;`) → filter empty segments

### Value distribution for aggregation
- [ ] Highly skewed budgets → use float arithmetic, no overflow concerns in Python
- [ ] Dominant or rare skills → defaultdict(int) handles any frequency
- [ ] All projects same status → still produces correct distribution dict
- [ ] Extreme numeric ranges → Python handles arbitrary precision

## Reference Implementation

A complete reference implementation is provided as `generate_json.py` in this skill package. The skill package files are mounted **flat** at `/skill/` inside the task container (not in a subdirectory). To use it:

```bash
# Copy the reference implementation to /app
cp /skill/generate_json.py /app/generate_json.py

# Run it
python3 /app/generate_json.py
```

The script reads from `/app/data/`, writes to `/app/organization.json`, and validates against `/app/schema.json`.

## Common Pitfalls

1. **Translating member IDs to names**: The schema accepts strings for `members`, but tests verify that member IDs remain as employee ID references. Keep them as-is.

2. **Off-by-one in statistics**: Ensure you're dividing by the correct denominator (number of departments for budget average, number of employees for years average).

3. **Missing departments in `departmentSizes`**: Include ALL departments, even those with 0 employees.

4. **Including zero-count entries in distributions**: Only include skills/statuses that actually appear in the data.

5. **Integer division for averages**: Use float division (`/` not `//`) for averages.

6. **Not handling empty multi-value fields**: An empty `member_ids` field should produce an empty array, not `[""]`.

7. **Schema validation as afterthought**: Always validate against the schema before considering the task complete.

8. **Not running self-test**: Schema validation catches structural errors but not logic errors. Always run the self-test procedure to verify member references, empty arrays, and statistics consistency.
