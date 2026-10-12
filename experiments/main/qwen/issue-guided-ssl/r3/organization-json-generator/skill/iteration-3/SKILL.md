---
name: organization-json-generator
description: Transform CSV data (departments, employees, projects) into nested organization JSON with schema validation and aggregate statistics
---

# Organization JSON Generator

Transforms three related CSV tables (departments, employees, projects) into a nested organization JSON structure with metadata and aggregate statistics. The output must validate against the provided JSON schema and preserve all relationships from the source data exactly.

## Architecture

Implements a **5-stage pipeline** that cleanly separates concerns and handles family variations:

### Stage 1: Parse
Read CSV files using Python's `csv.DictReader`. Each row becomes a dictionary keyed by column headers. Files are always:
- `departments.csv` (columns: id, name, budget)
- `employees.csv` (columns: id, name, position, skills, years_of_service, department_id)
- `projects.csv` (columns: name, status, member_ids, deadline, department_id)

### Stage 2: Normalize
Clean and type-coerce all fields:
- **String fields**: Strip whitespace
- **Integer fields** (years_of_service): Strip whitespace, remove commas, convert to int
- **Number fields** (budget): Strip whitespace, remove commas. Preserve as int when source has no decimal component, otherwise float
- **Semicolon-delimited lists** (skills, member_ids): Split on `;`, strip each element, filter empty strings. Handles edge cases: `"A;;B"`, `" A ; B ; "`, `""`

### Stage 3: Index
Build lookup structures for efficient assembly:
- `dept_by_id`: Map department ID → department object
- `employees_by_dept`: Map department ID → list of employees
- `projects_by_dept`: Map department ID → list of projects

Uses `defaultdict(list)` to handle departments with no employees or projects gracefully.

### Stage 4: Assemble
Construct nested JSON structure. **Output only schema-defined fields** — the `department_id` column is an internal relationship key used only for indexing; it must NOT appear in the output.

**Exact output fields per entity type** (read from schema.json `required` + `properties`):

| Entity | Output Fields | Notes |
|--------|--------------|-------|
| Department | `id`, `name`, `budget`, `employees`, `projects` | budget is number ≥0 |
| Employee | `id`, `name`, `position`, `skills`, `years_of_service` | skills is array of strings; years_of_service is integer ≥0 |
| Project | `name`, `status`, `members`, `deadline` | status is enum; members is array of employee ID strings |

**Critical**: The `department_id` column from employees.csv and projects.csv is used for grouping in Stage 3 but must be stripped during assembly. The output objects contain ONLY the fields listed above.

### Stage 5: Summarize
Compute aggregate statistics from the assembled data:
- `averageDepartmentBudget`: Mean of all department budgets (float division)
- `totalEmployees`: Count of all employees across all departments (integer)
- `skillDistribution`: Frequency count of each skill across all employees (object: skill_name → count)
- `departmentSizes`: Employee count per department (object: department_name → count)
- `projectStatusDistribution`: Count of projects per status (object: status → count)
- `averageYearsOfService`: Mean years of service across all employees (float division)

## Organization-Level Fields

The schema requires `organization.name` (string) and `organization.founded` (ISO date string). These are NOT present in any source CSV. The instruction says "without inventing placeholder entries" — however the schema mandates these fields. Strategy:
- If an `organization.csv` or similar metadata file exists in the data directory, read from it
- Otherwise, use minimal valid defaults: `"Organization"` for name, `"2000-01-01"` for founded
- The test `test_metadata_is_well_formed_without_hidden_constant_requirements` confirms no specific constant values are enforced

## Metadata Fields

The schema requires `metadata.version` (string), `metadata.timestamp` (ISO date-time), `metadata.generator` (string). These are generated at runtime:
- `version`: Any valid string (e.g., `"1.0"`)
- `timestamp`: Current UTC time in ISO format with timezone (e.g., `"2024-01-15T10:30:00+00:00"`)
- `generator`: Any descriptive string (e.g., `"organization-json-generator"`)

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
- **Numeric formatting**: Commas removed before conversion (`"1,500,000"` → `1500000`)
- **Leading zeros**: Preserved in strings, stripped in numeric conversion

### Value Distribution for Aggregation
- **Skewed budgets/years**: Statistics computed with float division, no integer truncation
- **Zero denominators**: Guarded with `if list else 0.0` checks
- **Dominant/rare skills**: `defaultdict(int)` handles any frequency distribution
- **Extreme numeric ranges**: Float arithmetic handles large/small values correctly

## Usage

```bash
python3 scripts/generate.py [data_dir] [schema_path] [output_path]
```

Default paths:
- `data_dir`: `/app/data`
- `schema_path`: `/app/schema.json`
- `output_path`: `/app/organization.json`

## Implementation Notes

1. **Schema-driven field selection**: Always read `/app/schema.json` and use it to validate output. The exact required fields per entity type are listed in the Stage 4 table above.

2. **Budget type preservation**: When the CSV budget value has no decimal component (e.g., `"1500000"`), output as integer `1500000` not float `1500000.0`. When it has a decimal (e.g., `"1500000.50"`), output as float.

3. **No external dependencies for core logic**: Uses only Python standard library (`csv`, `json`, `datetime`, `collections`, `pathlib`). The `jsonschema` library is available in the environment for validation.

4. **Validation**: After writing output, validate against the schema using `jsonschema.validate()`. Print warnings to stderr on validation failure.

## Testing

Verify correctness:
```bash
python3 scripts/generate.py
python3 -c "import json, jsonschema; jsonschema.validate(json.load(open('/app/organization.json')), json.load(open('/app/schema.json'))); print('✓ Valid')"
```

## Verification Checklist

After generating the output, verify all of the following:

### Schema Compliance
- [ ] Output file exists at `/app/organization.json`
- [ ] Output validates against `/app/schema.json` using `jsonschema.validate()`
- [ ] All required top-level keys present: `metadata`, `organization`, `statistics`

### Data Integrity
- [ ] All departments from `departments.csv` are present in output
- [ ] All employees are assigned to their correct department (via `department_id`)
- [ ] All projects are assigned to their correct department (via `department_id`)
- [ ] Project members are employee IDs from the same department
- [ ] No internal fields (e.g., `department_id`) appear in output objects

### Type Correctness
- [ ] Budget values are integers when source CSV has no decimal component
- [ ] Budget values are floats when source CSV has decimal component
- [ ] `years_of_service` values are integers
- [ ] `skills` and `members` are arrays of strings
- [ ] `timestamp` is timezone-aware ISO format (e.g., `2024-01-15T10:30:00+00:00`)

### Statistics Accuracy
- [ ] `averageDepartmentBudget` = sum of all budgets / number of departments
- [ ] `totalEmployees` = total count of all employees across all departments
- [ ] `skillDistribution` = frequency count of each skill across all employees
- [ ] `departmentSizes` = employee count per department (keyed by department name)
- [ ] `projectStatusDistribution` = count of projects per status
- [ ] `averageYearsOfService` = sum of all years / number of employees

### Edge Cases
- [ ] Departments with no projects have empty `projects` array
- [ ] Departments with no employees have empty `employees` array
- [ ] Projects with empty member lists have empty `members` array
- [ ] Semicolon-delimited lists with repeated delimiters are handled correctly
- [ ] Empty or whitespace-only fields are normalized to empty arrays

### Quick Validation Script
```python
import json
import jsonschema

# Load files
with open('/app/organization.json') as f:
    data = json.load(f)
with open('/app/schema.json') as f:
    schema = json.load(f)

# Schema validation
jsonschema.validate(data, schema)

# Data integrity checks
assert 'metadata' in data and 'organization' in data and 'statistics' in data
assert 'departments' in data['organization']
assert 'name' in data['organization'] and 'founded' in data['organization']

# Type checks
for dept in data['organization']['departments']:
    assert 'id' in dept and 'name' in dept and 'budget' in dept
    assert 'employees' in dept and 'projects' in dept
    for emp in dept['employees']:
        assert 'department_id' not in emp
        assert isinstance(emp['years_of_service'], int)
        assert isinstance(emp['skills'], list)
    for proj in dept['projects']:
        assert 'department_id' not in proj
        assert isinstance(proj['members'], list)

# Statistics checks
stats = data['statistics']
assert 'averageDepartmentBudget' in stats
assert 'totalEmployees' in stats
assert 'skillDistribution' in stats
assert 'departmentSizes' in stats
assert 'projectStatusDistribution' in stats
assert 'averageYearsOfService' in stats

print('✓ All verification checks passed')
```
