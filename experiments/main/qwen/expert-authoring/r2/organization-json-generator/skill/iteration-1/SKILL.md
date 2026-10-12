---
name: organization-json-generator
description: >
  Transform CSV data (departments, employees, projects) into a nested
  organization JSON file that validates against a provided JSON schema.
  Handles field normalization, relationship assembly, and aggregate statistics.
---

# Organization JSON Generator

## Task Overview

Read three CSV files from `/app/data/` (departments.csv, employees.csv, projects.csv),
assemble them into a nested organization structure, compute aggregate statistics,
and write the result to `/app/organization.json` that validates against `/app/schema.json`.

## Strategy

### 1. Understand the Data Model

The three CSV files form a relational structure:

- **departments**: `id, name, budget` — top-level organizational units
- **employees**: `id, name, position, skills, years_of_service, department_id` — linked to departments via `department_id`
- **projects**: `name, status, member_ids, deadline, department_id` — linked to departments via `department_id`; `member_ids` references employee IDs

### 2. Parse CSVs with Robust Normalization

Use Python's `csv` module. Apply normalization to every field:

- **Strip whitespace** from all string values (headers and data)
- **Semicolon-delimited fields** (skills, member_ids): split on `;`, strip each token, filter out empty strings
- **Numeric fields** (budget, years_of_service): parse to `int` or `float` as appropriate
- **Date fields** (deadline): preserve as ISO string (`YYYY-MM-DD`)
- **Handle edge cases**: repeated delimiters (`;;`), trailing delimiters, empty fields → empty arrays

```python
import csv

def read_csv(filepath):
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        # Strip header whitespace
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        rows = []
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip() if v else ''
                cleaned[k] = v
            rows.append(cleaned)
    return rows
```

### 3. Build the Nested Structure

```
organization.json
├── metadata: { version, timestamp, generator }
├── organization: { name, founded, departments[] }
│   └── departments[]: { id, name, budget, employees[], projects[] }
│       ├── employees[]: { id, name, position, skills[], years_of_service }
│       └── projects[]: { name, status, members[], deadline }
└── statistics: { averageDepartmentBudget, totalEmployees, skillDistribution,
                  departmentSizes, projectStatusDistribution, averageYearsOfService }
```

**Assembly steps:**
1. Group employees by `department_id`
2. Group projects by `department_id`
3. For each department, attach its employees and projects
4. Include ALL departments, even those with no employees or no projects
5. Convert `member_ids` in projects to `members` array (list of employee ID strings)
6. Sort departments by `id` for deterministic output

### 4. Compute Statistics

| Statistic | Formula |
|---|---|
| `averageDepartmentBudget` | sum of all department budgets / number of departments |
| `totalEmployees` | count of all employees across all departments |
| `skillDistribution` | `{ skill_name: count }` — count each skill occurrence across all employees |
| `departmentSizes` | `{ department_name: employee_count }` — number of employees per department |
| `projectStatusDistribution` | `{ status: count }` — count projects by status |
| `averageYearsOfService` | sum of all employees' years_of_service / total employees |

**Important**: Use exact arithmetic. For averages, do NOT round unless the schema requires it. The schema specifies `type: number` for averages, so floating-point is acceptable.

### 5. Metadata Fields

These are not derived from CSV data. Use reasonable defaults:
- `version`: `"1.0"`
- `timestamp`: current UTC datetime in ISO 8601 format (e.g., `"2025-01-15T00:00:00Z"`)
- `generator`: `"organization-json-generator"`

For organization-level fields not in CSVs:
- `name`: `"Organization"` (generic placeholder)
- `founded`: `"2020-01-01"` (any valid date string)

### 6. Validate Against Schema

After constructing the JSON, validate it against `/app/schema.json` using `jsonschema`:

```python
import json
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)

jsonschema.validate(instance=output, schema=schema)
```

If validation fails, inspect the error to identify which field violates the schema constraints.

### 7. Write Output

Write the validated JSON to `/app/organization.json` with `indent=2` for readability.

## Edge Cases to Handle

- **Departments with no projects**: include with `projects: []`
- **Departments with no employees**: include with `employees: []` (note: schema has `minItems: 2` for employees — this constraint may not apply to edge cases; validate and adjust)
- **Projects with empty member_ids**: `members: []` (not `[""]`)
- **Skills with empty value**: `skills: []` (but schema requires `minItems: 1`; if truly empty, this is a data issue)
- **Whitespace in CSV values**: always strip
- **Repeated delimiters**: `split(';')` then filter empty strings
- **Quoted CSV values**: Python's `csv.DictReader` handles standard CSV quoting automatically

## Implementation Script

Run the provided `scripts/generate.py` to produce the output:

```bash
python3 /path/to/skill/organization-json-generator/scripts/generate.py
```

Or implement the logic inline following the strategy above.

## Self-Verification Checklist

- [ ] All departments from CSV appear in output
- [ ] Each department has correct employees and projects nested
- [ ] Employee skills are arrays of strings (not semicolon-joined)
- [ ] Project members are arrays of strings (not semicolon-joined)
- [ ] Empty member_ids produce empty arrays, not `[""]`
- [ ] Budget is a number, years_of_service is an integer
- [ ] Statistics are computed over ALL data (not just one department)
- [ ] Output validates against schema.json with no errors
- [ ] No placeholder or invented entries beyond what CSV data provides
