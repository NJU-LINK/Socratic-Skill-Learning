---
name: organization-json-generator
description: >
  Transforms normalized CSV tables (departments, employees, projects) into a
  nested organization JSON that validates against a provided JSON Schema.
  Handles entity grouping by foreign key, semicolon-delimited multi-value
  fields, member-ID-to-name resolution, numeric type coercion, and aggregate
  statistics computation.
---

# Organization JSON Generator

## Task Overview

Read three CSV files from `/app/data/` — `departments.csv`, `employees.csv`,
`projects.csv` — and a JSON Schema from `/app/schema.json`. Produce
`/app/organization.json` that validates against the schema.

## Data Model (Family Invariants)

The CSV files form a three-table relational model. These structural properties
are **invariant across the family**:

| Table        | Key Columns                        | Foreign Keys                 |
|------------- |------------------------------------|------------------------------|
| departments  | `id`                               | —                            |
| employees    | `id`, multi-value `skills`         | `department_id` → departments |
| projects     | multi-value `member_ids`           | `department_id` → departments |

- `employees.skills` and `projects.member_ids` are **semicolon-delimited**
  strings that must become JSON arrays.
- `projects.member_ids` contains employee **IDs**; the output schema requires
  employee **names** in the `members` array.
- Every employee and project belongs to exactly one department, determined by
  `department_id`.

### Output Nesting

```
organization.json
├── metadata          (version, timestamp, generator)
├── organization
│   ├── name, founded (structural fields — see "Fields Not in CSV" below)
│   └── departments[]
│       ├── id, name, budget
│       ├── employees[]   (grouped by department_id)
│       └── projects[]    (grouped by department_id)
└── statistics         (aggregates over all departments)
```

## Fields Not in CSV

The schema requires `organization.name` (string) and `organization.founded`
(date). These are **not** present in any CSV. Use reasonable defaults — e.g.,
`"Organization"` and `"2000-01-01"`. The test validates schema conformance and
data correctness, not specific values for these structural fields.

Similarly, `metadata` fields (`version`, `timestamp`, `generator`) just need
to be schema-conformant. Use `datetime.now(UTC)` for the timestamp.

## Variation Dimensions

### 1. Entity Relationship Complexity

What varies: number of departments (≥ 3), employees per department (≥ 2),
projects per department (0 or more), project member counts (0 or more).

**Decision rules:**
- A department with no matching projects → `projects: []` (empty array, not
  omitted).
- A project with empty `member_ids` → `members: []`.
- The same employee can appear in multiple projects.
- Department order in the output should follow the CSV row order.

### 2. Field Parsing and Normalization

What varies: whitespace around values, repeated delimiters (`;;`), empty
multi-value fields, quoted text, numeric formatting (commas in numbers,
decimal vs integer strings).

**Normalization checklist (apply to every field):**
1. Strip leading/trailing whitespace from all keys and values.
2. Split multi-value fields on `;`, strip each part, **filter empty strings**.
3. Numeric fields: strip whitespace, remove commas, strip quotes, then parse.
   - `budget` → `number` (float or int).
   - `years_of_service` → `integer` (truncate/round if needed).
4. Quoted strings: strip surrounding quotes after whitespace removal.

### 3. Value Distribution for Aggregation

What varies: magnitude and skew of budgets, years of service, skill
frequency, project status concentration.

**The required statistics are always the same six metrics:**

| Statistic                    | Formula                                            | Type    |
|----------------------------- |--------------------------------------------------- |---------|
| `averageDepartmentBudget`   | `sum(budgets) / len(departments)`                  | number  |
| `totalEmployees`            | `sum(len(d.employees) for d in departments)`       | integer |
| `skillDistribution`         | `{ skill: count_of_employees_with_that_skill }`    | object  |
| `departmentSizes`           | `{ dept_name: len(employees) }`                    | object  |
| `projectStatusDistribution` | `{ status: count_of_projects_with_that_status }`   | object  |
| `averageYearsOfService`     | `sum(all_years) / total_employees`                 | number  |

**Key correctness points:**
- `skillDistribution` counts each skill **once per employee** who has it.
- `departmentSizes` is keyed by department **name**, not ID.
- `projectStatusDistribution` only includes statuses that actually appear.
- Averages should be full-precision floats (do not round).
- `totalEmployees` must be an `int`, not a float.

## Implementation Strategy

Write a single Python script at `/app/generate.py` and execute it.

### Step-by-Step Algorithm

```
1. READ departments.csv, employees.csv, projects.csv
     → apply whitespace stripping to all keys and values

2. BUILD lookup: employee_by_id = { emp.id: emp for emp in employees }

3. GROUP employees by department_id → employees_by_dept
   GROUP projects  by department_id → projects_by_dept

4. FOR each department (in CSV order):
     a. Parse budget → number
     b. Collect employees for this dept:
          - Split skills on ";", strip, filter empties → array
          - Parse years_of_service → int
     c. Collect projects for this dept:
          - Split member_ids on ";", strip, filter empties
          - Resolve each ID to employee name via employee_by_id
            (fallback: keep the raw ID if no match)
          - Map status directly (validate against enum if desired)

5. COMPUTE statistics over the assembled department list

6. ASSEMBLE output dict with metadata + organization + statistics

7. WRITE to /app/organization.json (indent=2)

8. VALIDATE against /app/schema.json using jsonschema (if available)
```

### Robust Parsing Functions

```python
def parse_semicolon_list(value):
    """Semicolon-delimited → list of non-empty stripped strings."""
    if not value or not value.strip():
        return []
    return [p for p in (item.strip() for item in value.split(";")) if p]

def parse_number(value):
    """String → int or float, handling commas, quotes, whitespace."""
    v = value.strip().strip('"').strip("'").replace(",", "")
    try:
        return int(v) if "." not in v else float(v)
    except ValueError:
        return float(v) if v else 0
```

## Self-Verification Checklist

After generating the JSON, verify **before submitting**:

1. **Schema validation** passes (`jsonschema.validate`).
2. `totalEmployees` equals `sum(len(d["employees"]) for d in departments)`.
3. `departmentSizes[name]` equals `len(employees)` for every department.
4. `averageDepartmentBudget` equals `sum(budgets) / num_departments`.
5. `averageYearsOfService` equals `sum(years) / total_employees`.
6. Every project member is a **name** (not an ID like `D001-E002`).
7. Departments with no projects have `projects: []` (not missing key).
8. Projects with no members have `members: []` (not missing key).
9. All `skills` arrays are non-empty (schema requires `minItems: 1`).
10. `budget` is a number, `years_of_service` is an integer.

## Reference Script

A complete reference implementation is provided at
`scripts/generate.py`. To use it:

```bash
python3 skill/organization-json-generator/scripts/generate.py
```

The script reads from `/app/data/`, validates against `/app/schema.json`,
and writes to `/app/organization.json`.
