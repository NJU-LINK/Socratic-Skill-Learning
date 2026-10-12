---
name: organization-json-generator
description: >
  Transform multiple related CSV files (departments, employees, projects) into a
  single nested organization JSON document that validates against a provided JSON
  schema. Handles cross-table joins, semicolon-delimited multi-value fields,
  robust numeric/string normalization, and aggregate statistics computation.
---

# Organization JSON Generator

## Task Summary

Read three CSV files from `/app/data/` — `departments.csv`, `employees.csv`, and
`projects.csv` — plus a JSON schema from `/app/schema.json`, and produce
`/app/organization.json` that validates against the schema.

The output is a nested structure:
- **metadata**: version, timestamp, generator
- **organization**: name, founded date, and an array of departments
  - Each department contains its employees and projects
- **statistics**: aggregate metrics computed from the assembled data

## Architecture

```
departments.csv ──┐
employees.csv  ───┼──▶ [Parse & Normalize] ──▶ [Join & Nest] ──▶ [Statistics] ──▶ organization.json
projects.csv   ───┘                                                                        ▲
schema.json ────────────────────────────────────────────────────────────────────────────────┘
                                                                                   (validation)
```

## Step-by-Step Methodology

### 1. Read and Parse CSV Files

Use Python's `csv.DictReader` to read each CSV. Apply these normalizations to every field:
- **Strip whitespace** from all keys and values
- Handle BOM (`utf-8-sig` encoding)
- Handle quoted fields (DictReader does this automatically)
- Handle repeated delimiters and empty multi-value fields

```python
import csv

def read_csv(filepath):
    rows = []
    with open(filepath, 'r', newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                if k is None:
                    continue
                cleaned[k.strip()] = v.strip() if v else ''
            rows.append(cleaned)
    return rows
```

### 2. Parse Multi-Value Fields

Skills and member_ids are semicolon-delimited. Parse them robustly:

```python
def parse_semicolon_list(value):
    if not value:
        return []
    parts = [p.strip() for p in value.split(';')]
    return [p for p in parts if p]  # filter empty strings from repeated delimiters
```

### 3. Parse Numeric Fields

Budgets and years_of_service need type-appropriate parsing:
- **budget**: number (int when whole, float when fractional). Schema requires `minimum: 0`.
- **years_of_service**: integer. Schema requires `minimum: 0`.

```python
import math

def parse_number(value):
    v = value.strip().replace(',', '')
    if not v:
        return 0
    f = float(v)
    if f == math.floor(f) and not math.isinf(f):
        return int(f)
    return f

def parse_int(value):
    return int(value.strip().replace(',', ''))
```

### 4. Build Cross-Table Relationships

The three CSVs are linked by foreign keys:
- `employees.department_id` → `departments.id`
- `projects.department_id` → `departments.id`
- `projects.member_ids` → `employees.id` (semicolon-delimited)

Build lookup structures:

```python
# Employee lookup by ID (used for grouping employees by department)
employee_by_id = {}
for emp in employees_raw:
    employee_by_id[emp['id']] = emp

# Group employees by department
employees_by_dept = defaultdict(list)
for emp in employee_by_id.values():
    employees_by_dept[emp['department_id']].append(emp)

# Group projects by department
projects_by_dept = defaultdict(list)
for proj in projects_raw:
    projects_by_dept[proj['department_id']].append(proj)
```

### 5. Preserve Project Member References

The CSV stores `member_ids` (semicolon-delimited employee IDs like
`D001-E001;D001-E002`). The schema field is `members` (array of strings).

**Keep the original employee ID strings as-is.** The task instruction says
"preserve the relationships represented by the source data exactly" — the
source data represents project membership via employee IDs, so the `members`
array should contain those same ID strings. This is the lossless, deterministic
choice: IDs are always unique and unambiguous, whereas names could collide.

```python
member_ids = parse_semicolon_list(proj.get('member_ids', ''))
# Use member_ids directly as the members array — no name resolution
```

Projects may have empty member lists (e.g., Planning-stage projects). This is
valid per the schema (no `minItems` on members).

### 6. Assemble Nested Department Objects

For each department row, create the nested structure:

```python
dept_obj = {
    'id': dept['id'],
    'name': dept['name'],
    'budget': parse_number(dept['budget']),
    'employees': [...],  # from employees_by_dept
    'projects': [...]    # from projects_by_dept, with member IDs preserved
}
```

Key points:
- Departments with no projects get an empty `projects` array
- All employees for a department are included (the data guarantees ≥2 per dept)
- Skills must have ≥1 entry (schema `minItems: 1`); if CSV has empty skills, use a placeholder

### 7. Compute Statistics

Six statistics are required:

| Statistic | Formula |
|---|---|
| `averageDepartmentBudget` | `sum(budgets) / len(departments)` |
| `totalEmployees` | `sum(len(dept.employees) for dept in departments)` |
| `skillDistribution` | Count how many employees possess each skill |
| `departmentSizes` | Employee count per department, keyed by department **name** |
| `projectStatusDistribution` | Count of projects per status value |
| `averageYearsOfService` | `sum(years) / total_employees` |

**Important details:**
- `averageDepartmentBudget`: return int if result is whole number, float otherwise
- `averageYearsOfService`: typically a float; do NOT round unless schema requires it
- `skillDistribution`: each skill string → count of employees who have it
- `departmentSizes`: keys are department **names** (not IDs)
- `projectStatusDistribution`: keys are status enum values ("Planning", "In Progress", etc.)

### 8. Fill Metadata and Organization-Level Fields

These fields are not in the CSV data:

| Field | Value |
|---|---|
| `metadata.version` | `"1.0"` (any valid string) |
| `metadata.timestamp` | Current UTC datetime in ISO 8601 format |
| `metadata.generator` | `"organization-json-generator"` (any descriptive string) |
| `organization.name` | `"Organization"` (any non-empty string) |
| `organization.founded` | `"2000-01-01"` (any valid ISO date) |

### 9. Validate and Write

```python
import jsonschema

with open(schema_path) as f:
    schema = json.load(f)
jsonschema.validate(output, schema)

with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
```

## Handling Variation Dimensions

### Entity Relationship Complexity

The skill must handle any valid relationship pattern:
- **Departments with no projects**: produce empty `projects: []`
- **Departments with many employees/projects**: no special handling needed; grouping handles any count
- **Projects with empty member lists**: `parse_semicolon_list('')` returns `[]`
- **Dense member reuse**: member IDs are kept as literal strings, so overlap patterns work regardless of density
- **Cross-department references**: member_ids are preserved verbatim from the source data

### Field Parsing and Normalization

Robust parsing handles:
- **Extra whitespace**: all fields are `.strip()`-ed
- **Repeated delimiters**: `";;"` produces empty strings that are filtered out
- **Empty multi-value fields**: return empty list `[]`
- **Quoted text**: `csv.DictReader` handles CSV quoting natively
- **Numeric formatting**: commas in numbers are stripped; whole-number floats become ints
- **BOM characters**: `utf-8-sig` encoding handles BOM

### Value Distribution for Aggregation

Statistics computation is distribution-agnostic:
- **Skewed budgets/years**: simple sum/count works regardless of distribution
- **Dominant/rare skills**: defaultdict(int) counts correctly
- **Concentrated statuses**: same counting logic
- **Extreme ranges**: Python handles arbitrary precision integers and floats
- **Zero-employee departments**: guarded with `if total_employees > 0` checks

## Schema Constraints to Remember

- `organization.departments`: `minItems: 3`
- `department.employees`: `minItems: 2`
- `employee.skills`: `minItems: 1` (must have at least one skill)
- `employee.years_of_service`: integer, `minimum: 0`
- `department.budget`: number, `minimum: 0`
- `project.status`: enum `["Planning", "In Progress", "Testing", "Completed", "On Hold"]`
- `project.members`: array of strings (no minItems — can be empty)
- `metadata.timestamp`: format `date-time`
- `organization.founded`: format `date`

## Complete Reference Implementation

See `scripts/generate.py` for a complete, tested implementation.
