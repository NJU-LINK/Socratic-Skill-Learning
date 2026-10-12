---
name: organization-json-generator
description: Transform CSV data (departments, employees, projects) into a nested organization JSON structure with metadata and aggregate statistics, conforming to a JSON schema.
---

# Organization JSON Generator

## Quick Start Workflow

When solving a variant of this task, follow this workflow:

1. **Read `/app/schema.json` first** - This is your source of truth for field names, types, enums, and constraints. The schema structure is consistent across variants, but always verify the exact requirements.
2. **Read the CSV files** - Examine `/app/data/departments.csv`, `/app/data/employees.csv`, `/app/data/projects.csv` to understand the data structure.
3. **Implement the transformation** - Use the implementation method below, adapting to what the schema requires.
4. **Validate against schema** - Use `jsonschema.validate()` to ensure conformance.
5. **Verify statistics manually** - Compute a few statistics by hand to check correctness.

**Key principle**: The schema.json file is always provided and is the authoritative specification. Your implementation must conform to it, not to memorized assumptions.

## Task Family Overview

This skill handles the transformation of relational CSV data into a nested JSON structure representing an organization. The task involves:

1. **Reading and parsing** three CSV files: departments, employees, and projects
2. **Normalizing fields**: converting semicolon-delimited strings to arrays, parsing numeric values, handling whitespace
3. **Assembling nested structure**: grouping employees and projects under their respective departments
4. **Computing statistics**: aggregating data across the organization (averages, totals, distributions)
5. **Generating metadata**: adding version, timestamp, and generator information
6. **Validating output**: ensuring the JSON conforms to the provided schema

## Schema-Driven Development

The schema.json file at `/app/schema.json` is always provided and is the authoritative specification for the output. Your implementation must:

1. **Read the schema first** to understand required fields, types, enums, and constraints
2. **Conform to the schema** - field names, types, and structure must match exactly
3. **Validate the output** using `jsonschema.validate(data, schema)` before submission

**Important**: The schema structure (field names, types, required fields) is consistent across the task family - this is part of the shared task semantics. What varies is the data: different numbers of departments/employees/projects, different field values, different formatting challenges. Always read the schema to confirm the exact requirements, but you can rely on the overall structure being consistent.

### Interpreting JSON Schema

The schema uses JSON Schema Draft-07. Key constructs to understand:

- **`required`**: Array of field names that must be present. Example: `"required": ["metadata", "organization"]` means both fields are mandatory.

- **`type`**: Specifies the data type. Common values:
  - `"string"`: Text value
  - `"number"`: Floating-point or integer (e.g., 1500000 or 1500000.0)
  - `"integer"`: Whole number only (e.g., 10, not 10.0)
  - `"object"`: Nested JSON object with properties
  - `"array"`: List of items

- **`properties`**: Defines the structure of an object. Each key is a field name, and its value is another schema describing that field.

- **`enum`**: Array of allowed values. Example: `"enum": ["Planning", "In Progress"]` means the field must be one of those exact strings.

- **`format`**: Specifies string format. Common values:
  - `"date"`: ISO 8601 date (e.g., "2020-01-01")
  - `"date-time"`: ISO 8601 datetime (e.g., "2020-01-01T12:00:00Z")

- **`items`**: For arrays, defines the schema of each element. Example: `"items": {"type": "string"}` means an array of strings.

- **`minItems` / `maxItems`**: For arrays, minimum and maximum number of elements.

- **`minimum` / `maximum`**: For numbers, minimum and maximum values.

- **`additionalProperties`**: For objects, defines schema for any properties not explicitly listed. Example: `"additionalProperties": {"type": "integer"}` means the object can have any keys, but all values must be integers.

**Example**: To extract the required statistics fields from the schema:
```python
import json

with open('/app/schema.json') as f:
    schema = json.load(f)

# Navigate to statistics schema
stats_schema = schema['properties']['statistics']
required_stats = stats_schema['required']
# Result: ['averageDepartmentBudget', 'totalEmployees', ...]
```

This tells you exactly which statistics to compute, without hardcoding assumptions.

For fields required by the schema but not present in the CSV data (like `organization.name` and `organization.founded`), use reasonable defaults. The tests typically validate type conformance, not specific values, unless the schema or task description specifies otherwise.

## Variation Dimensions

### 1. Entity Relationship Complexity

**What varies**: How rows across CSV files relate to each other before assembly into the nested structure.

**Family invariants**:
- Three-table structure: departments, employees, projects
- Employees and projects reference departments via `department_id`
- Each department contains its employees and projects as nested arrays
- The nesting hierarchy is always: organization → departments → [employees, projects]

**Expected variations**:
- Departments with no projects (empty projects array)
- Departments with many more projects or employees than the seed
- Projects with empty member lists (empty members array)
- Denser project-member reuse patterns (employees appearing in multiple projects)
- Different cardinalities (2-3 employees per department in seed, but could be more)

**Handling strategy**:
- Use `defaultdict(list)` to group employees and projects by department_id
- Always include all departments from departments.csv, even if they have no employees or projects
- Parse member_ids as semicolon-delimited list; empty string → empty array
- The structure naturally handles any cardinality

### 2. Field Parsing and Normalization

**What varies**: How much cleaning and type normalization is required when converting CSV fields to JSON values.

**Family invariants**:
- Skills and member_ids are semicolon-delimited strings that must become arrays
- Budget must be a number (not string)
- years_of_service must be an integer (not string)
- All string fields should be trimmed of whitespace

**Expected variations**:
- Extra whitespace around values (e.g., " Python " → "Python")
- Repeated delimiters (e.g., "Python;;Leadership" → ["Python", "Leadership"])
- Empty multi-value fields (e.g., empty skills or member_ids)
- Quoted text in CSV (handled by csv.DictReader)
- Numeric strings with different formatting (e.g., "1,500,000" → 1500000, "10.0" → 10)
- Mixed case or inconsistent formatting
- Missing CSV fields (csv.DictReader assigns None, must be coerced to empty string)

**Handling strategy**:
- Strip whitespace from all CSV keys and values after reading
- Coerce `None` values to empty string (csv.DictReader assigns None for missing fields)
- Split on semicolons, strip each part, filter out empty strings
- Use defensive `parse_int()` for years_of_service (handles "10.0", "1,000")
- Use `parse_number()` for budget (preserves int type for whole numbers, handles commas)
- Let csv.DictReader handle quoted fields automatically

### 3. Value Distribution for Aggregation

**What varies**: How challenging it is to compute statistics due to the size and distribution of values.

**Family invariants**:
- Required statistics:
  - `averageDepartmentBudget`: mean of all department budgets
  - `totalEmployees`: count of all employees across all departments
  - `skillDistribution`: frequency count of each skill across all employees
  - `departmentSizes`: employee count per department (keyed by department name)
  - `projectStatusDistribution`: frequency count of each project status
  - `averageYearsOfService`: mean of all employees' years_of_service
- Statistics are computed from the assembled data, not directly from CSVs

**Expected variations**:
- Highly skewed budgets or years_of_service values (e.g., one department with budget 100x others)
- Dominant or rare skills (e.g., "Communication" appearing in 90% of employees)
- Heavily concentrated project statuses (e.g., 90% "In Progress")
- Extreme numeric ranges (e.g., years_of_service from 0 to 50)
- Small vs. large datasets (affects floating point precision)

**Handling strategy**:
- Compute statistics from the assembled dept_records structure
- Use simple aggregation: sum/count for averages, defaultdict(int) for distributions
- Compute averages with full floating-point precision; tests typically compare values rounded to 2 decimal places
- Guard against division by zero (e.g., no employees → average is 0.0)
- Statistics keys must match schema exactly (camelCase names)

## Implementation Method

### Step 1: Read and Parse CSVs

```python
import csv
from collections import defaultdict

def read_csv(filepath):
    """Read CSV with whitespace stripping and None coercion."""
    rows = []
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {}
            for k, v in row.items():
                key = k.strip() if k else k
                # Coerce None to '' (DictReader assigns None for missing fields)
                val = v.strip() if v is not None else ''
                cleaned[key] = val
            rows.append(cleaned)
    return rows
```

### Step 2: Parse Delimited Fields

```python
def parse_semicolon_list(value):
    """Parse semicolon-delimited string to list, filtering empty values."""
    if not value or not value.strip():
        return []
    parts = value.split(';')
    return [p.strip() for p in parts if p.strip()]
```

### Step 3: Parse Numeric Fields

```python
def parse_int(value):
    """Parse string to integer, handling float-formatted and comma-formatted numbers."""
    if value is None:
        return 0
    cleaned = value.strip().replace(',', '')
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        # Handle "10.0" → 10, "10.7" → 10
        return int(float(cleaned))

def parse_number(value):
    """Parse string to number. Returns int if whole, float otherwise.
    Handles comma separators and whitespace."""
    if value is None:
        return 0
    cleaned = value.strip().replace(',', '')
    try:
        return int(cleaned)
    except ValueError:
        return float(cleaned)
```

**Important**: 
- Use `parse_int()` for `years_of_service` — it handles "10.0" and "1,000" by routing through `float` first, then truncating to int as the schema requires.
- Use `parse_number()` for budget fields to preserve integer type when the CSV contains whole numbers. This avoids outputting `1500000.0` when `1500000` is expected.

### Step 4: Build Nested Structure

```python
def build_organization(departments_csv, employees_csv, projects_csv):
    departments = read_csv(departments_csv)
    employees = read_csv(employees_csv)
    projects = read_csv(projects_csv)
    
    # Group employees by department_id
    emp_by_dept = defaultdict(list)
    for emp in employees:
        dept_id = emp.get('department_id', '').strip()
        emp_by_dept[dept_id].append({
            'id': emp['id'].strip(),
            'name': emp['name'].strip(),
            'position': emp['position'].strip(),
            'skills': parse_semicolon_list(emp.get('skills', '')),
            'years_of_service': parse_int(emp.get('years_of_service', '0'))
        })
    
    # Group projects by department_id
    proj_by_dept = defaultdict(list)
    for proj in projects:
        dept_id = proj.get('department_id', '').strip()
        member_ids = parse_semicolon_list(proj.get('member_ids', ''))
        proj_by_dept[dept_id].append({
            'name': proj['name'].strip(),
            'status': proj['status'].strip(),
            'members': member_ids,
            'deadline': proj['deadline'].strip()
        })
    
    # Build department records
    dept_records = []
    for dept in departments:
        dept_id = dept['id'].strip()
        dept_record = {
            'id': dept_id,
            'name': dept['name'].strip(),
            'budget': parse_number(dept.get('budget', '0')),
            'employees': emp_by_dept.get(dept_id, []),
            'projects': proj_by_dept.get(dept_id, [])
        }
        dept_records.append(dept_record)
    
    return dept_records
```

### Step 5: Compute Statistics

```python
def compute_statistics(dept_records):
    # Average department budget
    budgets = [d['budget'] for d in dept_records]
    avg_budget = sum(budgets) / len(budgets) if budgets else 0.0
    
    # Total employees
    total_employees = sum(len(d['employees']) for d in dept_records)
    
    # Skill distribution
    skill_dist = defaultdict(int)
    for d in dept_records:
        for emp in d['employees']:
            for skill in emp['skills']:
                skill_dist[skill] += 1
    
    # Department sizes (keyed by department name)
    dept_sizes = {}
    for d in dept_records:
        dept_sizes[d['name']] = len(d['employees'])
    
    # Project status distribution
    status_dist = defaultdict(int)
    for d in dept_records:
        for proj in d['projects']:
            status_dist[proj['status']] += 1
    
    # Average years of service
    all_years = []
    for d in dept_records:
        for emp in d['employees']:
            all_years.append(emp['years_of_service'])
    avg_years = sum(all_years) / len(all_years) if all_years else 0.0
    
    return {
        'averageDepartmentBudget': avg_budget,
        'totalEmployees': total_employees,
        'skillDistribution': dict(skill_dist),
        'departmentSizes': dept_sizes,
        'projectStatusDistribution': dict(status_dist),
        'averageYearsOfService': avg_years
    }
```

### Step 6: Assemble Final Output

```python
from datetime import datetime, timezone

output = {
    'metadata': {
        'version': '1.0',
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'generator': 'organization-json-generator'
    },
    'organization': {
        'name': 'Organization',
        'founded': '2020-01-01',
        'departments': dept_records
    },
    'statistics': statistics
}
```

**Note on organization.name and organization.founded**: These fields are required by the v01 schema but not present in the CSV data. Use reasonable defaults:
- `name`: "Organization" or any descriptive string
- `founded`: Any valid date string (e.g., "2020-01-01")

The tests typically validate that these fields exist and are valid types, not specific values. **Always check the schema** — if a variant's schema specifies particular values or derivation rules, follow those instead.

### Step 7: Write JSON Output

```python
import json

with open('/app/organization.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
```

## Key Schema Requirements (v01 Reference)

The output must validate against the provided JSON schema. **Always read `/app/schema.json` at runtime** — the constraints below are for v01 and may vary in other variants. Key v01 constraints:

- **metadata**: version (string), timestamp (date-time string), generator (string)
- **organization**: name (string), founded (date string), departments (array, minItems: 3)
- **department**: id, name, budget (number ≥ 0), employees (array, minItems: 2), projects (array)
- **employee**: id, name, position, skills (array, minItems: 1), years_of_service (integer ≥ 0)
- **project**: name, status (enum: Planning/In Progress/Testing/Completed/On Hold), members (array), deadline (date string)
- **statistics**: All six required fields with correct types

**Schema-driven checklist**:
- [ ] Read schema.json before implementing
- [ ] Match all required field names exactly (camelCase)
- [ ] Ensure all type constraints are met (number vs integer vs string)
- [ ] Verify enum values match schema
- [ ] Check minItems/maxItems constraints
- [ ] Validate output with jsonschema before submission

## Common Pitfalls

1. **Forgetting to convert types**: Budget and years_of_service must be numbers, not strings
2. **Not handling empty delimited fields**: Empty member_ids should produce empty array, not [""]
3. **Incorrect statistic keys**: Must match schema exactly (camelCase)
4. **Missing departments**: All departments from CSV must appear, even with no employees/projects
5. **Incorrect grouping**: Employees and projects must be grouped by department_id, not included at top level
6. **Whitespace in parsed values**: Always strip whitespace from CSV values and delimited list items
7. **None values from csv.DictReader**: Rows with fewer fields than the header get None values; coerce to empty string before any `.strip()` call
8. **Float-formatted integers**: years_of_service might be "10.0" in CSV; route through `float()` then `int()` to avoid crashes
9. **Comma-formatted numbers**: Budgets like "1,500,000" need comma removal before numeric conversion

## Testing Approach

After generating the JSON:

1. **Validate against schema**: Use jsonschema library to check conformance
2. **Check relationships**: Verify employees appear under correct departments
3. **Verify statistics**: Manually compute a few statistics to ensure correctness
4. **Check edge cases**: Empty arrays for departments with no projects/employees

```python
import jsonschema

with open('/app/schema.json') as f:
    schema = json.load(f)

with open('/app/organization.json') as f:
    data = json.load(f)

jsonschema.validate(data, schema)
print("Valid!")
```

## Complete Script

See `generate.py` in this skill package for a complete, working implementation.

To run:
```bash
python3 generate.py
```

The script reads from `/app/data/*.csv` and writes to `/app/organization.json`. Paths can be overridden via environment variables: `DATA_DIR`, `SCHEMA_PATH`, `OUTPUT_PATH`.
