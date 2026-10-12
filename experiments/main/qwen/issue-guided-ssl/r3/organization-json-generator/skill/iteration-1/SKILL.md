---
name: organization-json-generator
description: Transform CSV data (departments, employees, projects) into nested organization JSON with schema validation and aggregate statistics
---

# Organization JSON Generator

Transforms three related CSV tables (departments, employees, projects) into a nested organization JSON structure with metadata and aggregate statistics.

## Architecture

Implements a **5-stage pipeline** that cleanly separates concerns and handles family variations:

### Stage 1: Parse
Read CSV files using Python's `csv.DictReader`. Each row becomes a dictionary keyed by column headers.

### Stage 2: Normalize
Clean and type-coerce all fields:
- **String fields**: Strip whitespace
- **Integer fields** (years_of_service): Strip whitespace, remove commas, convert to int
- **Number fields** (budget): Strip whitespace, remove commas, convert to float
- **Semicolon-delimited lists** (skills, member_ids): Split on `;`, strip each element, filter empty strings. Handles edge cases: `"A;;B"`, `" A ; B ; "`, `""`

### Stage 3: Index
Build lookup structures for efficient assembly:
- `dept_by_id`: Map department ID → department object
- `employees_by_dept`: Map department ID → list of employees
- `projects_by_dept`: Map department ID → list of projects

Uses `defaultdict(list)` to handle departments with no employees or projects gracefully.

### Stage 4: Assemble
Construct nested JSON structure:
- Each department contains its employees array and projects array
- Remove internal fields (e.g., `department_id`) that aren't part of the output schema
- Handle empty arrays for departments with no projects or projects with no members

### Stage 5: Summarize
Compute aggregate statistics from the assembled data:
- `averageDepartmentBudget`: Mean of all department budgets
- `totalEmployees`: Count of all employees across all departments
- `skillDistribution`: Frequency count of each skill across all employees
- `departmentSizes`: Employee count per department (keyed by department name)
- `projectStatusDistribution`: Count of projects per status
- `averageYearsOfService`: Mean years of service across all employees

## Family Variation Handling

### Entity Relationship Complexity
- **Departments with no projects**: Handled via `defaultdict(list)` — returns empty array
- **Departments with no employees**: Same mechanism — returns empty array
- **Projects with empty member lists**: Semicolon-list normalization returns `[]` for empty/whitespace-only fields
- **Dense member reuse**: Members are stored as employee ID strings; no deduplication needed
- **Variable department sizes**: Index stage handles arbitrary counts

### Field Parsing and Normalization
- **Whitespace**: All string fields stripped via `normalize_string()`
- **Repeated delimiters**: `"Python;;Java"` → `["Python", "Java"]` (empty elements filtered)
- **Empty multi-value fields**: `""` or `";;"` → `[]`
- **Quoted text**: Handled by CSV parser
- **Numeric formatting**: Commas removed before conversion (`"1,500,000"` → `1500000.0`)
- **Leading zeros**: Preserved in strings, stripped in numeric conversion

### Value Distribution for Aggregation
- **Skewed budgets/years**: Statistics computed with float division, no integer truncation
- **Zero denominators**: Guarded with `if list else 0.0` checks
- **Dominant/rare skills**: `defaultdict(int)` handles any frequency distribution
- **Extreme numeric ranges**: Float arithmetic handles large/small values correctly

## Schema Compliance

Output validates against JSON Schema draft-07 with these key constraints:
- **metadata**: version (string), timestamp (ISO date-time), generator (string)
- **organization**: name (string), founded (ISO date), departments (array, minItems 3)
- **departments**: id, name, budget (number ≥0), employees (array, minItems 2), projects (array)
- **employees**: id, name, position, skills (array of strings, minItems 1), years_of_service (integer ≥0)
- **projects**: name, status (enum), members (array of strings), deadline (ISO date)
- **statistics**: All six required aggregate metrics

## Usage

```bash
python3 scripts/generate.py [data_dir] [schema_path] [output_path]
```

Default paths:
- `data_dir`: `/app/data`
- `schema_path`: `/app/schema.json`
- `output_path`: `/app/organization.json`

## Implementation Notes

1. **Organization metadata**: `organization.name` and `organization.founded` are required by schema but not present in source CSVs. Uses defaults: `"Organization"` and `"2000-01-01"`.

2. **Field cleanup**: Internal relationship fields (e.g., `department_id` in employees/projects) are removed during assembly to match the output schema exactly.

3. **No external dependencies**: Uses only Python standard library (`csv`, `json`, `datetime`, `collections`, `pathlib`).

4. **Validation**: Output is validated against the schema using `jsonschema` library (available in environment).

## Testing

Verify correctness:
```bash
python3 scripts/generate.py
python3 -c "import json, jsonschema; jsonschema.validate(json.load(open('/app/organization.json')), json.load(open('/app/schema.json'))); print('✓ Valid')"
```
