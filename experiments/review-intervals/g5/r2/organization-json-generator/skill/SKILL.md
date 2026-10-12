---
name: organization-json-generator
description: >
  Transforms CSV data files (departments, employees, projects) into a nested
  organization JSON structure conforming to a provided JSON schema. Handles
  entity relationship assembly, field parsing/normalization, and aggregate
  statistics computation.
---

# Organization JSON Generator

## Purpose

Transform relational CSV data into a nested JSON organization structure with metadata and statistics.

## Quick Start (Use This)

The skill package includes a complete, tested implementation at `/skill/generate.py`. Inside the task container, the skill files are mounted at `/skill/`.

**Do exactly this:**

```bash
cp /skill/generate.py /app/generate.py
python3 /app/generate.py
```

That's it. The script will:
1. Read the three CSV files from `/app/data/`
2. Assemble the nested organization structure
3. Compute all required statistics
4. Write `/app/organization.json`
5. Validate against `/app/schema.json`

**Do NOT** read the CSV files or schema manually. The bundled script handles everything.

If the script fails or you need to debug, see the "Troubleshooting" section below.

## What the Script Does

### Input Files

- `/app/data/departments.csv`: `id`, `name`, `budget`
- `/app/data/employees.csv`: `id`, `name`, `position`, `skills`, `years_of_service`, `department_id`
- `/app/data/projects.csv`: `name`, `status`, `member_ids`, `deadline`, `department_id`
- `/app/schema.json`: JSON schema defining the output structure

### Output Structure

```json
{
  "metadata": {
    "version": "1.0.0",
    "timestamp": "2025-01-15T00:00:00Z",
    "generator": "organization-json-generator"
  },
  "organization": {
    "name": "Organization",
    "founded": "2020-01-01",
    "departments": [
      {
        "id": "D001",
        "name": "Engineering",
        "budget": 1500000,
        "employees": [...],
        "projects": [...]
      }
    ]
  },
  "statistics": {
    "averageDepartmentBudget": 1000000.0,
    "totalEmployees": 14,
    "skillDistribution": {"Python": 4, ...},
    "departmentSizes": {"Engineering": 3, ...},
    "projectStatusDistribution": {"In Progress": 3, ...},
    "averageYearsOfService": 6.93
  }
}
```

### Key Mechanisms

1. **CSV Parsing**: Strips whitespace from all keys/values, handles quoted fields
2. **Semicolon-Delimited Lists**: Parses `skills` and `member_ids` fields, filters empty strings
3. **Entity Relationships**: Groups employees and projects by `department_id`, attaches to departments
4. **Numeric Types**: Preserves int vs float (budgets without decimals → int, with decimals → float)
5. **Statistics**: Computes averages (float division), counts, distributions in a single pass
6. **Edge Cases**: Departments with no projects → empty array, projects with no members → empty array

## Troubleshooting

If the script fails:

1. **Check that `/skill/generate.py` exists**: `ls -la /skill/`
2. **Check that input files exist**: `ls -la /app/data/`
3. **Read the error message**: The script validates against the schema and reports failures
4. **Read the schema**: `cat /app/schema.json` to understand requirements
5. **Manual implementation**: If the bundled script doesn't work, you'll need to write your own. See the "Manual Implementation Guide" below.

## Manual Implementation Guide

**Only use this if the bundled script fails.**

### Step 1: Read the Schema

```bash
cat /app/schema.json
```

Pay attention to:
- Required fields at each level
- Data types (string, number, integer, array, object)
- Format constraints (date, date-time)
- Enum values (project status)
- Minimum array lengths (minItems)

### Step 2: Examine the Data

```bash
cat /app/data/departments.csv
cat /app/data/employees.csv
cat /app/data/projects.csv
```

Note:
- Semicolon-delimited lists (skills, member_ids)
- Empty fields (projects with no members)
- Numeric formats

### Step 3: Write the Script

Key code patterns:

**CSV parsing with normalization:**
```python
import csv

def read_csv(filepath):
    rows = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                key = k.strip() if k else k
                val = v.strip() if v else ''
                cleaned[key] = val
            rows.append(cleaned)
    return rows
```

**Semicolon-delimited list parsing:**
```python
def parse_semicolon_list(value):
    if not value or not value.strip():
        return []
    parts = [p.strip() for p in value.split(';')]
    return [p for p in parts if p]
```

**Numeric parsing (preserve int vs float):**
```python
def parse_number(value):
    val = value.strip()
    if '.' in val:
        return float(val)
    return int(val)
```

**Entity relationship assembly:**
```python
from collections import defaultdict

emp_by_dept = defaultdict(list)
for emp in employees:
    emp_by_dept[emp['department_id']].append(emp_record)

proj_by_dept = defaultdict(list)
for proj in projects:
    proj_by_dept[proj['department_id']].append(proj_record)

for dept in departments:
    dept_record = {
        "employees": emp_by_dept.get(dept['id'], []),
        "projects": proj_by_dept.get(dept['id'], [])
    }
```

**Statistics computation:**
```python
def compute_statistics(dept_records):
    total_employees = 0
    total_years = 0
    total_budget = 0
    skill_counts = defaultdict(int)
    dept_sizes = {}
    status_counts = defaultdict(int)

    for dept in dept_records:
        total_budget += dept['budget']
        emp_count = len(dept['employees'])
        total_employees += emp_count
        dept_sizes[dept['name']] = emp_count
        
        for emp in dept['employees']:
            total_years += emp['years_of_service']
            for skill in emp['skills']:
                skill_counts[skill] += 1
        
        for proj in dept['projects']:
            status_counts[proj['status']] += 1

    num_depts = len(dept_records)
    avg_budget = total_budget / num_depts if num_depts > 0 else 0.0
    avg_years = total_years / total_employees if total_employees > 0 else 0.0

    return {
        "averageDepartmentBudget": avg_budget,
        "totalEmployees": total_employees,
        "skillDistribution": dict(skill_counts),
        "departmentSizes": dept_sizes,
        "projectStatusDistribution": dict(status_counts),
        "averageYearsOfService": avg_years
    }
```

**Metadata generation:**
```python
from datetime import datetime, timezone

timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

output = {
    "metadata": {
        "version": "1.0.0",
        "timestamp": timestamp,
        "generator": "organization-json-generator"
    },
    "organization": {
        "name": "Organization",
        "founded": "2020-01-01",
        "departments": dept_records
    },
    "statistics": statistics
}
```

### Step 4: Validate

```python
import json
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)
with open('/app/organization.json') as f:
    data = json.load(f)

jsonschema.validate(data, schema)
print("Validation passed!")
```

## Common Pitfalls

1. **Integer vs float budgets**: CSV has `1500000` but `float('1500000')` gives `1500000.0`. Check if value has decimal point before parsing.

2. **Empty project members**: Don't omit the `members` key; include it as `[]`.

3. **Department sizes keying**: Use department name (not ID) as the key.

4. **Statistics denominator**: Use total_employees for averageYearsOfService, not num_departments.

5. **Timestamp format**: Must be ISO 8601 with timezone (e.g., `2025-01-15T00:00:00Z`).

6. **Schema-first approach**: Always read the schema before writing code. Don't assume field names or structure.

## Family Variation Handling

### Entity Relationship Complexity

- **Departments with no projects**: Handled by `.get(dept_id, [])` → empty array
- **Departments with many projects/employees**: No special handling needed; grouping scales
- **Projects with empty member lists**: `parse_semicolon_list('')` → `[]`
- **Dense member reuse**: No special handling; member_ids are just strings in an array

### Field Parsing and Normalization

- **Extra whitespace**: Stripped during CSV reading
- **Repeated delimiters**: Filtered by `parse_semicolon_list`
- **Empty multi-value fields**: Return empty arrays
- **Quoted text**: Handled by csv.DictReader
- **Numeric formatting**: `parse_number` handles int vs float

### Value Distribution for Aggregation

- **Skewed budgets/years**: Float division handles any range
- **Dominant/rare skills**: defaultdict(int) counts correctly
- **Concentrated statuses**: Same defaultdict pattern
- **Extreme numeric ranges**: Python handles arbitrary precision
