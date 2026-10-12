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
            'years_of_service': int(emp['years_of_service'])
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
        'budget': float(dept['budget']),
        'employees': employees_by_dept.get(dept_id, []),
        'projects': projects_by_dept.get(dept_id, [])
    }
    dept_records.append(dept_record)
```

### 5. Statistics Computation

Compute all statistics from the **assembled nested data**, not separately from raw CSVs. This ensures consistency and handles edge cases correctly.

```python
# Average department budget
total_departments = len(dept_records)
total_budget = sum(d['budget'] for d in dept_records)
avg_budget = total_budget / total_departments if total_departments > 0 else 0.0

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

# Average years of service
total_years = sum(emp['years_of_service'] for emp in all_employees)
avg_years = total_years / total_employees if total_employees > 0 else 0.0
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
- Numeric strings with different formatting (converted via `int()` or `float()`)

### Value Distribution for Aggregation

Computing statistics from assembled data handles:
- **Skewed budgets/years**: Division by count, not assumptions about distribution
- **Dominant/rare skills**: `defaultdict(int)` counts all occurrences
- **Concentrated statuses**: Same counting mechanism
- **Extreme numeric ranges**: Python handles arbitrary precision

## Validation

Always validate the output against the provided schema:

```python
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)
with open('/app/organization.json') as f:
    data = json.load(f)

jsonschema.validate(data, schema)
```

## Common Pitfalls

1. **Empty string splitting**: `"".split(";")` → `[""]` not `[]`. Always check for empty/whitespace before splitting.

2. **Missing departments**: Don't skip departments with no employees or projects. They must appear with empty arrays.

3. **Statistics from raw vs assembled data**: Compute from assembled nested structure to ensure consistency.

4. **Metadata placeholders**: The schema requires metadata fields not in CSVs. Use fixed sensible values, not invented data rows.

5. **Project members**: Use raw employee IDs from CSV, not transformed values. The field is `member_ids` in CSV, `members` in JSON.

6. **Dictionary keys for statistics**: Use department **names** (not IDs) for `departmentSizes`, matching the pattern of skill names and status strings.
