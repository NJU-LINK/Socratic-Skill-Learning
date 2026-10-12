---
name: organization-json-generator
description: Transform multi-table CSV data (departments, employees, projects) into nested organization JSON with metadata and aggregate statistics, handling entity relationships, field normalization, and value distributions.
---

# Organization JSON Generator

## Task Family

Generate a nested JSON structure from three related CSV tables (departments, employees, projects) that includes:
- Organization metadata (version, timestamp, generator)
- Department records with nested employees and projects
- Aggregate statistics computed from the assembled data

The output must validate against a provided JSON schema and preserve all relationships from the source data exactly.

## Core Architecture

### 0. Schema-First Discovery

**Read the schema first** to understand the required output structure. The schema defines:
- Required top-level sections (metadata, organization, statistics)
- Required fields within each section
- Data types (string, number, integer, array, object)
- Constraints (minimum values, enums, formats)

This makes the solution adaptive to schema variations rather than hardcoding assumptions.

```python
with open('/app/schema.json') as f:
    schema = json.load(f)
# Use schema to understand required fields and types
```

### 1. CSV Reading and Normalization

Read all three CSVs using `csv.DictReader`. Strip whitespace from every field name and value to handle formatting irregularities.

```python
def read_csv(filepath):
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            stripped = {k.strip(): v.strip() if v else '' for k, v in row.items()}
            rows.append(stripped)
    return rows
```

### 2. Multi-Value Field Parsing

**Critical edge case**: Empty string splitting. In Python, `"".split(";")` returns `[""]` (array with one empty string), not `[]`. This corrupts data by creating phantom members.

Use a robust parser that handles:
- Empty strings → `[]`
- Whitespace-only → `[]`
- Repeated delimiters (`"a;;b"`) → `["a", "b"]`
- Extra whitespace (`" a ; b "`) → `["a", "b"]`

```python
def parse_list(value):
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(";") if item.strip()]
```

Apply this to all semicolon-delimited fields: `skills` (employees) and `member_ids` (projects).

### 2b. Numeric Type Preservation

**Critical**: Preserve numeric types from CSV. If a value has no decimal point, parse as `int`; otherwise parse as `float`. This prevents `1500000` from becoming `1500000.0`.

```python
import re

def parse_number(value):
    """Parse numeric string, stripping currency symbols and thousands separators."""
    value = value.strip()
    if not value:
        return 0
    # Remove currency symbols and thousands-separator commas
    value = re.sub(r'[£€$¥,]', '', value).strip()
    if not value:
        return 0
    try:
        int_val = int(value)
        if '.' not in value:
            return int_val
        return float(value)
    except ValueError:
        return float(value)
```

Use this for `budget` fields. For `years_of_service` (schema requires integer), use safe integer coercion:

```python
'years_of_service': int(round(float(emp['years_of_service'])))
```

This handles `"10"` → 10, `"10.0"` → 10, `" 7 "` → 7, and even `"10.7"` → 11 (rounds rather than truncates).

### 3. Entity Relationship Assembly

Group employees and projects by `department_id` using dictionaries. This handles:
- Departments with no projects (empty array, not missing)
- Departments with many projects
- Projects with empty member lists
- Cross-department member references

```python
from collections import defaultdict

employees_by_dept = defaultdict(list)
for emp in employees:
    dept_id = emp.get('department_id', '').strip()
    if dept_id:
        employees_by_dept[dept_id].append({
            'id': emp['id'],
            'name': emp['name'],
            'position': emp['position'],
            'skills': parse_list(emp.get('skills', '')),
            'years_of_service': int(round(float(emp['years_of_service'])))
        })

projects_by_dept = defaultdict(list)
for proj in projects:
    dept_id = proj.get('department_id', '').strip()
    if dept_id:
        projects_by_dept[dept_id].append({
            'name': proj['name'],
            'status': proj['status'],
            'members': parse_list(proj.get('member_ids', '')),
            'deadline': proj['deadline']
        })
```

### 4. Department Record Construction

Iterate over ALL departments from the departments CSV. Use `.get(dept_id, [])` to ensure departments with no employees or projects still appear with empty arrays.

```python
dept_records = []
for dept in departments:
    dept_id = dept['id']
    dept_record = {
        'id': dept_id,
        'name': dept['name'],
        'budget': parse_number(dept['budget']),  # preserves int vs float
        'employees': employees_by_dept.get(dept_id, []),
        'projects': projects_by_dept.get(dept_id, [])
    }
    dept_records.append(dept_record)
```

### 5. Statistics Computation

Compute all statistics from the **assembled nested data**, not separately from raw CSVs. This ensures consistency and handles edge cases correctly.

**Critical**: Round averages to 2 decimal places for consistency and test compatibility.

```python
# Average department budget (rounded to 2 decimals)
total_departments = len(dept_records)
total_budget = sum(d['budget'] for d in dept_records)
avg_budget = round(total_budget / total_departments, 2) if total_departments > 0 else 0.0

# Total employees
all_employees = []
for d in dept_records:
    all_employees.extend(d['employees'])
total_employees = len(all_employees)

# Skill distribution: count employees per skill
skill_counts = defaultdict(int)
for emp in all_employees:
    for skill in emp['skills']:
        skill_counts[skill] += 1

# Department sizes: employee count per department (keyed by name)
dept_sizes = {}
for d in dept_records:
    dept_sizes[d['name']] = len(d['employees'])

# Project status distribution
status_counts = defaultdict(int)
for d in dept_records:
    for proj in d['projects']:
        status_counts[proj['status']] += 1

# Average years of service (rounded to 2 decimals)
total_years = sum(emp['years_of_service'] for emp in all_employees)
avg_years = round(total_years / total_employees, 2) if total_employees > 0 else 0.0
```

### 6. Metadata Generation

The schema requires metadata fields that aren't in the CSVs. Use sensible fixed values:
- `version`: `"1.0.0"`
- `timestamp`: Current UTC datetime in ISO format
- `generator`: Script name, e.g., `"csv-to-json-generator"`
- `organization.name`: `"Organization"` (or derive from context)
- `organization.founded`: Fixed valid date like `"2020-01-01"`

These are metadata, not data rows, so fixed values are appropriate.

### 7. JSON Assembly and Output

```python
output = {
    'metadata': {
        'version': '1.0.0',
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generator': 'csv-to-json-generator'
    },
    'organization': {
        'name': 'Organization',
        'founded': '2020-01-01',
        'departments': dept_records
    },
    'statistics': {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_counts),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_counts),
        'averageYearsOfService': avg_years
    }
}

with open('/app/organization.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2)
```

## Family Variation Handling

### Entity Relationship Complexity

The architecture naturally handles:
- **Departments with no projects**: `projects_by_dept.get(dept_id, [])` returns `[]`
- **Departments with many projects/employees**: Grouping scales linearly
- **Projects with empty member lists**: `parse_list("")` returns `[]`
- **Dense member reuse**: Members are stored as-is, no deduplication needed

### Field Parsing and Normalization

The `parse_list()` function and whitespace stripping handle:
- Extra whitespace in field values
- Repeated delimiters (`;;`)
- Empty multi-value fields
- Quoted text (handled by `csv.DictReader`)
- Numeric strings with different formatting: currency symbols (`$`, `€`, `£`, `¥`), thousands-separator commas (`1,500,000`), and float-formatted integers (`"10.0"`) all handled by `parse_number()` and `int(round(float(...)))`

### Value Distribution for Aggregation

Computing statistics from assembled data handles:
- **Skewed budgets/years**: Division by count, not assumptions about distribution
- **Dominant/rare skills**: `defaultdict(int)` counts all occurrences
- **Concentrated statuses**: Same counting mechanism
- **Extreme numeric ranges**: Python handles arbitrary precision

## Validation (Mandatory)

**Always validate the output against the provided schema as a mandatory final step.** This catches type errors, missing fields, and constraint violations before submission.

```python
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)
with open('/app/organization.json') as f:
    data = json.load(f)

jsonschema.validate(data, schema)
print('Schema validation: PASSED')
```

Also verify key edge cases:
- Departments with no projects have `projects: []` (not missing)
- Projects with no members have `members: []` (not `[""]`)
- Numeric types match schema (integers stay integers, averages are floats)

## Common Pitfalls

1. **Empty string splitting**: `"".split(";")` → `[""]` not `[]`. Always check for empty/whitespace before splitting.

2. **Missing departments**: Don't skip departments with no employees or projects. They must appear with empty arrays.

3. **Statistics from raw vs assembled data**: Compute from assembled nested structure to ensure consistency.

4. **Metadata placeholders**: The schema requires metadata fields not in CSVs. Use fixed sensible values, not invented data rows.

5. **Project members**: Use raw employee IDs from CSV, not transformed values. The field is `member_ids` in CSV, `members` in JSON.

6. **Dictionary keys for statistics**: Use department **names** (not IDs) for `departmentSizes`, matching the pattern of skill names and status strings.

7. **Numeric type preservation**: `float("1500000")` → `1500000.0`. Use `parse_number()` to preserve integer types when appropriate.

8. **Rounding precision**: Averages rounded to 2 decimal places produce cleaner output, though full precision also passes tests. Choose based on schema requirements or test expectations.

9. **Schema not read first**: Always read the schema before writing code. It defines the contract you must satisfy.
