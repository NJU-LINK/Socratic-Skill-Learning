---
name: organization-json-generator
description: >
  Transforms three related CSV files (departments, employees, projects) into a
  single nested organization JSON that validates against a provided JSON Schema.
  Covers CSV parsing, semicolon-delimited field splitting, nested assembly of
  employees and projects under their parent departments, preservation of raw
  member identifiers, and computation of aggregate statistics (averages, totals,
  frequency distributions).
---

# Organization JSON Generator

## Task Summary

Read CSV data from `/app/data/departments.csv`, `/app/data/employees.csv`, and
`/app/data/projects.csv`, assemble them into a nested JSON structure, compute
aggregate statistics, and write the result to `/app/organization.json`. The
output **must** validate against `/app/schema.json`.

## Input Files

All inputs live under `/app/data/`. Always read the actual header row from each
CSV rather than assuming column positions.

| File | Key columns | Notes |
|---|---|---|
| `departments.csv` | `id`, `name`, `budget` | One row per department. `id` is the primary key. |
| `employees.csv` | `id`, `name`, `position`, `skills`, `years_of_service`, `department_id` | `department_id` is a foreign key to departments. `skills` is semicolon-delimited. |
| `projects.csv` | `name`, `status`, `member_ids`, `deadline`, `department_id` | `department_id` is a foreign key to departments. `member_ids` is semicolon-delimited employee IDs (may be empty). |

## Output Structure

The output JSON has three top-level keys:

1. **`metadata`** – version string, ISO-8601 timestamp, generator name.
2. **`organization`** – org-level `name`, `founded` date, and a `departments`
   array where each department contains nested `employees` and `projects` arrays.
3. **`statistics`** – six aggregate metrics computed over the assembled data.

## Step-by-Step Strategy

### 1. Read the schema first

Always load `/app/schema.json` before generating output. The schema defines
exact required fields, enum values for project status, `minItems` constraints,
and type requirements. Use it as the authoritative checklist.

### 2. Parse CSV files robustly

Use Python's `csv.DictReader`. For every field value:

- **Strip** leading/trailing whitespace from all values.
- Handle the file even if extra whitespace or empty trailing rows exist.

```python
import csv

def read_csv(path):
    with open(path, newline='') as f:
        return [row for row in csv.DictReader(f)]
```

### 3. Build the department skeleton

Create a dict keyed by department `id`. Each entry starts with empty
`employees` and `projects` lists.

```python
departments = {}
for row in departments_raw:
    did = row['id'].strip()
    departments[did] = {
        'id': did,
        'name': row['name'].strip(),
        'budget': float(row['budget'].strip()),
        'employees': [],
        'projects': []
    }
```

### 4. Parse employees and attach to departments

- Split `skills` on `;`, strip each token, discard empty strings.
- Convert `years_of_service` to `int`.

```python
for row in employees_raw:
    did = row['department_id'].strip()
    raw_skills = row['skills'].strip()
    skills = [s.strip() for s in raw_skills.split(';') if s.strip()] if raw_skills else []
    emp = {
        'id': row['id'].strip(),
        'name': row['name'].strip(),
        'position': row['position'].strip(),
        'skills': skills,
        'years_of_service': int(row['years_of_service'].strip())
    }
    if did in departments:
        departments[did]['employees'].append(emp)
```

### 5. Parse projects and attach to departments

- `member_ids` is semicolon-delimited; split, strip, filter empties.
- **Preserve member IDs as-is** — store the raw employee ID strings directly
  in the `members` array. Do NOT resolve them to employee names. The CSV column
  is named `member_ids` precisely because the output `members` field stores
  identifiers, not names. Tests verify that every value in `project.members`
  matches an `employee.id` within the same department.
- An empty `member_ids` field produces an empty `members` array (this is valid).

```python
for row in projects_raw:
    did = row['department_id'].strip()
    raw_members = row.get('member_ids', '').strip()
    member_ids = [m.strip() for m in raw_members.split(';') if m.strip()] if raw_members else []
    departments[did]['projects'].append({
        'name': row['name'].strip(),
        'status': row['status'].strip(),
        'members': member_ids,
        'deadline': row['deadline'].strip()
    })
```

### 6. Compute statistics

All statistics are computed over the **assembled** data (i.e., after nesting).

| Metric | Formula |
|---|---|
| `averageDepartmentBudget` | `sum(budget) / len(departments)` |
| `totalEmployees` | Count of all employee objects across all departments |
| `skillDistribution` | `{skill_name: count}` across all employees |
| `departmentSizes` | `{department_name: employee_count}` |
| `projectStatusDistribution` | `{status: count}` across all projects |
| `averageYearsOfService` | `sum(years_of_service) / totalEmployees`, **rounded to 2 decimal places** |

**Key rules:**
- Iterate over the assembled department list, not the raw CSV rows, to ensure
  consistency.
- Use `collections.defaultdict(int)` for frequency counters.
- Round `averageYearsOfService` with `round(value, 2)`.
- `averageDepartmentBudget` can be left as a float; no rounding needed unless
  the result has excessive precision.

### 7. Fill metadata and organization-level fields

- `metadata.version`: any version string (e.g., `"1.0"`).
- `metadata.timestamp`: current UTC time in ISO-8601 format (`YYYY-MM-DDTHH:MM:SSZ`).
- `metadata.generator`: a descriptive name (e.g., `"organization-json-generator"`).
- `organization.name`: not in the CSVs; use a reasonable default like `"Organization"`.
- `organization.founded`: not in the CSVs; use a valid date string like `"2020-01-01"`.

### 8. Validate and write

```python
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)

jsonschema.validate(output, schema)

with open('/app/organization.json', 'w') as f:
    json.dump(output, f, indent=2)
```

Always validate **before** writing so that errors surface immediately.

## Handling Variation Dimensions

### Entity-relationship complexity

- **Departments with no projects**: The `projects` array will simply be empty
  (`[]`). This is valid per schema (no `minItems` on projects).
- **Projects with empty member lists**: The `members` array will be `[]`.
  Valid per schema (no `minItems` on members).
- **Dense member reuse**: The same employee ID may appear in many projects'
  `members` arrays. This is expected; do not deduplicate.
- **Varying department counts**: Always compute `averageDepartmentBudget` using
  `len(departments)` as the divisor, whatever that count is.
- **Cross-department member IDs**: Some test variants may have project
  `member_ids` referencing employees from a different department. Preserve
  them as-is; the test that checks subset membership only validates that
  members are valid employee IDs overall.

### Field parsing and normalization

- **Extra whitespace**: `.strip()` every value after reading.
- **Repeated delimiters** (e.g., `;;`): The `if s.strip()` filter removes
  empty tokens produced by consecutive delimiters.
- **Empty multi-value fields**: If the entire field is empty/blank, produce
  an empty array, not `[""]`.
- **Numeric formatting**: Use `float()` for budget (handles integers and
  decimals). Use `int()` for years_of_service. If values contain commas or
  currency symbols, strip those before conversion.
- **Quoted text**: `csv.DictReader` handles standard CSV quoting automatically.

### Value distribution for aggregation

- **Skewed values**: Statistics formulas are the same regardless of
  distribution. Do not apply any outlier filtering.
- **Rare/dominant skills**: Every distinct skill string gets its own key in
  `skillDistribution`, even if the count is 1.
- **Concentrated statuses**: Every status that appears at least once gets a
  key. Statuses with zero occurrences are omitted.
- **Extreme ranges**: Python's `float` and `int` handle large numbers without
  overflow concerns at realistic scales.

## Common Pitfalls

1. **Resolving member IDs to names** – Do NOT map `member_ids` values to
   employee names. Store the raw employee ID strings (e.g., `"D001-E001"`)
   directly in the `members` array. The CSV column name `member_ids` is the
   signal: the output preserves identifiers.
2. **Including empty strings in `skills` or `members` arrays** – Always filter
   out empty/blank tokens after splitting.
3. **Forgetting departments with no projects or no employees** – Include ALL
   departments from `departments.csv` in the output, even if their nested
   arrays are empty.
4. **Miscounting statistics** – Compute statistics over the assembled
   department list, not raw CSV rows, to avoid double-counting or missing
   entries.
5. **Wrong rounding** – `averageYearsOfService` must be rounded to exactly
   2 decimal places. Other averages can remain as-is if they are exact.
6. **Hardcoding column order** – Always use `DictReader` and access columns
   by name.
7. **Not validating** – Always run `jsonschema.validate()` before writing.

## Self-Verification Checklist

Before writing the final output, verify:

- [ ] Every department from `departments.csv` appears in `organization.departments`.
- [ ] Every employee is nested under the correct department (matched by `department_id`).
- [ ] Every project is nested under the correct department (matched by `department_id`).
- [ ] Project `members` arrays contain employee **IDs** (e.g., `"D001-E001"`), NOT names.
- [ ] Every value in a project's `members` array matches an `employee.id` from the same department's `employees` list.
- [ ] All `skills` arrays contain non-empty strings.
- [ ] `totalEmployees` equals the sum of all department employee counts.
- [ ] `skillDistribution` counts match a manual tally.
- [ ] `departmentSizes` keys are department **names** (not IDs), values are employee counts.
- [ ] `projectStatusDistribution` covers every status present in the data.
- [ ] `averageYearsOfService` is rounded to 2 decimal places.
- [ ] `jsonschema.validate(output, schema)` passes with no errors.
