---
name: organization-json-generator
description: >
  Transform CSV data (departments, employees, projects) into a nested
  organization JSON file that validates against a provided JSON schema.
  Handles field normalization, relationship assembly, and aggregate statistics.
---

# Organization JSON Generator

## Quick Start

**Run the bundled script directly** — it handles all normalization, assembly,
statistics, and schema validation:

```bash
python3 <skill-base-dir>/scripts/generate.py
```

If you need to implement inline (e.g., the script is unavailable), follow the
full strategy below. **Do not use bare `int()` or `float()` on CSV values** —
always use the `parse_number` helper shown in Section 2.

## 1. Workflow Overview

```
1. Read /app/schema.json        → discover required structure, types, constraints
2. Read CSVs from /app/data/    → departments.csv, employees.csv, projects.csv
3. Normalize every field        → strip, split delimiters, parse numbers safely
4. Assemble nested JSON         → group by department_id, attach employees/projects
5. Compute statistics           → averages, totals, distributions over ALL data
6. Validate against schema      → catch type/constraint errors before writing
7. Write /app/organization.json
```

## 2. Robust Field Parsing

**This is the highest-risk area for variant data.** CSV values may contain
extra whitespace, commas in numbers, float representations of integers,
repeated delimiters, or empty fields.

```python
import csv
from collections import defaultdict
from datetime import datetime, timezone

def read_csv(filepath):
    """Read CSV with robust header and value stripping."""
    rows = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                k = k.strip()
                v = v.strip() if v else ''
                cleaned[k] = v
            rows.append(cleaned)
    return rows

def parse_number(raw):
    """Parse a numeric string that may contain commas, decimals, or whitespace.
    
    Returns int when the value is a whole number, float otherwise.
    This is critical: the schema requires 'integer' for years_of_service
    and 'number' for budget.  Using bare int() crashes on '1500000.0'
    or '1,500,000'.
    
    Examples:
        '1500000'    → 1500000 (int)
        '1500000.0'  → 1500000 (int, not float)
        '1,500,000'  → 1500000 (int)
        '6.93'       → 6.93 (float)
        ''           → 0
    """
    if not raw:
        return 0
    # Remove commas and whitespace
    cleaned = raw.replace(',', '').strip()
    if not cleaned:
        return 0
    # Try int first
    try:
        return int(cleaned)
    except ValueError:
        pass
    # Try float, then convert to int if it's actually a whole number
    try:
        f = float(cleaned)
        return int(f) if f == int(f) else f
    except ValueError:
        return 0

def parse_list(raw, delimiter=';'):
    """Split a delimited string into non-empty stripped tokens.
    
    Handles: empty string, repeated delimiters (;;), trailing delimiters,
    leading/trailing whitespace on individual tokens.
    """
    if not raw or not raw.strip():
        return []
    return [t.strip() for t in raw.split(delimiter) if t.strip()]
```

**Key decision rules for type coercion:**

| Schema type    | CSV might contain       | Use this                  |
|----------------|-------------------------|---------------------------|
| `"integer"`    | `"10"`, `"10.0"`, `"10,000"` | `parse_number()` → always returns int for whole numbers |
| `"number"`     | `"1500000"`, `"1500000.50"`  | `parse_number()` → int when whole, float when fractional |
| `"string"`     | `" Engineering "`, `'"Quoted"'` | `.strip()` — csv.DictReader handles standard quoting |
| `"array"`      | `"A;B;C"`, `"A;;B"`, `""`     | `parse_list()` — filter empty tokens |

## 3. Data Model

The three CSVs form a relational structure linked by `department_id`:

```
departments.csv   → id, name, budget
employees.csv     → id, name, position, skills, years_of_service, department_id
projects.csv      → name, status, member_ids, deadline, department_id
```

- `employees.department_id` → FK to `departments.id`
- `projects.department_id`  → FK to `departments.id`
- `projects.member_ids`     → semicolon-delimited employee IDs (from employees.id)

## 4. Assembly

```python
# Read all CSVs
departments = read_csv('/app/data/departments.csv')
employees   = read_csv('/app/data/employees.csv')
projects    = read_csv('/app/data/projects.csv')

# Parse into typed records
dept_list = []
for d in departments:
    dept_list.append({
        'id': d['id'],
        'name': d['name'],
        'budget': parse_number(d.get('budget', '0')),
    })

emp_records = []
for e in employees:
    emp_records.append({
        'id': e['id'],
        'name': e['name'],
        'position': e.get('position', ''),
        'skills': parse_list(e.get('skills', '')),
        'years_of_service': parse_number(e.get('years_of_service', '0')),
        'department_id': e['department_id'],
    })

proj_records = []
for p in projects:
    proj_records.append({
        'name': p['name'],
        'status': p.get('status', ''),
        'members': parse_list(p.get('member_ids', '')),
        'deadline': p.get('deadline', ''),
        'department_id': p['department_id'],
    })

# Group by department_id
emp_by_dept = defaultdict(list)
for e in emp_records:
    emp_by_dept[e['department_id']].append(e)

proj_by_dept = defaultdict(list)
for p in proj_records:
    proj_by_dept[p['department_id']].append(p)

# Build nested structure — sorted by department id for determinism
nested_depts = []
for dept in sorted(dept_list, key=lambda d: d['id']):
    did = dept['id']
    nested_depts.append({
        'id': did,
        'name': dept['name'],
        'budget': dept['budget'],
        'employees': [
            {
                'id': e['id'],
                'name': e['name'],
                'position': e['position'],
                'skills': e['skills'],
                'years_of_service': e['years_of_service'],
            }
            for e in emp_by_dept.get(did, [])
        ],
        'projects': [
            {
                'name': p['name'],
                'status': p['status'],
                'members': p['members'],
                'deadline': p['deadline'],
            }
            for p in proj_by_dept.get(did, [])
        ],
    })
```

**Invariants:**
- ALL departments appear, even those with no employees or no projects
- Empty `member_ids` → `members: []` (never `[""]`)
- Empty `skills` → `skills: []` (schema requires `minItems: 1` — data should always have at least one)

## 5. Statistics

| Statistic | Formula | Type |
|---|---|---|
| `averageDepartmentBudget` | `sum(budgets) / len(departments)` | number |
| `totalEmployees` | count of all employee records | integer |
| `skillDistribution` | `{skill: count}` across ALL employees | object→integer |
| `departmentSizes` | `{dept_name: employee_count}` | object→integer |
| `projectStatusDistribution` | `{status: count}` across ALL projects | object→integer |
| `averageYearsOfService` | `sum(years) / totalEmployees` | number |

**Critical**: compute over ALL data, not per-department. Do not round unless
the schema demands it (it doesn't — `type: number` accepts float).

```python
total_budget = sum(d['budget'] for d in nested_depts)
n_depts = len(nested_depts)

all_employees = [e for d in nested_depts for e in d['employees']]
all_projects  = [p for d in nested_depts for p in d['projects']]

skill_dist = defaultdict(int)
for e in all_employees:
    for s in e['skills']:
        skill_dist[s] += 1

dept_sizes = {d['name']: len(d['employees']) for d in nested_depts}

status_dist = defaultdict(int)
for p in all_projects:
    status_dist[p['status']] += 1

total_years = sum(e['years_of_service'] for e in all_employees)
n_emps = len(all_employees)

statistics = {
    'averageDepartmentBudget': total_budget / n_depts if n_depts else 0,
    'totalEmployees': n_emps,
    'skillDistribution': dict(skill_dist),
    'departmentSizes': dept_sizes,
    'projectStatusDistribution': dict(status_dist),
    'averageYearsOfService': total_years / n_emps if n_emps else 0,
}
```

## 6. Metadata and Organization Fields

These fields are not derived from CSV data. Use fixed defaults:

```python
output = {
    'metadata': {
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generator': 'organization-json-generator',
    },
    'organization': {
        'name': 'Organization',
        'founded': '2020-01-01',
        'departments': nested_depts,
    },
    'statistics': statistics,
}
```

## 7. Schema Validation

**Always validate before writing.** This catches type mismatches, missing
required fields, and enum violations immediately.

```python
import json
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)

try:
    jsonschema.validate(instance=output, schema=schema)
except jsonschema.ValidationError as e:
    print(f"VALIDATION FAILED: {e.message}")
    print(f"  Path: {list(e.absolute_path)}")
    # Fix the issue and re-validate before writing
    raise

with open('/app/organization.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
    f.write('\n')
```

## 8. Edge-Case Decision Table

| Situation | Action |
|---|---|
| Department with no projects | `projects: []` |
| Department with no employees | `employees: []` |
| Project with empty `member_ids` | `members: []` — never `[""]` |
| Employee with empty `skills` | `skills: []` — but schema needs `minItems:1` |
| Budget is `"1,500,000"` | `parse_number` → `1500000` |
| Years is `"10.0"` | `parse_number` → `10` (int) |
| Whitespace in values | Always `.strip()` |
| Repeated delimiters `A;;B` | `parse_list` → `["A", "B"]` |
| Quoted CSV values | `csv.DictReader` handles standard quoting |
| Extra columns in CSV | Ignore — only extract known fields |

## 9. Self-Verification Checklist

After writing output, verify:

- [ ] Schema validation passes (use jsonschema)
- [ ] Number of departments in output matches departments.csv row count
- [ ] Sum of employees across departments matches employees.csv row count
- [ ] Sum of projects across departments matches projects.csv row count
- [ ] No empty strings in any `members` or `skills` arrays
- [ ] All `budget` values are numbers (not strings)
- [ ] All `years_of_service` values are integers (not floats or strings)
- [ ] `totalEmployees` statistic equals actual employee count
- [ ] `skillDistribution` sums equal total skill slots across all employees
- [ ] `projectStatusDistribution` sums equal total project count
