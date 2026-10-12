---
name: organization-json-generator
description: >
  Transform multi-table CSV data (departments, employees, projects) into a
  nested organization JSON with metadata, hierarchical department records, and
  aggregate statistics. Handles variable entity relationships, field
  normalization, and distribution-robust aggregation.
---

# Organization JSON Generator

## Purpose

Convert relational CSV data (departments, employees, projects) into a nested
JSON structure conforming to a provided JSON schema. The output includes:
- Organization metadata (version, timestamp, generator)
- Hierarchical department records with nested employees and projects
- Aggregate statistics computed over the assembled data

## Task Interface

**Input files** (in `/app/data/`):
- `departments.csv` — columns: `id`, `name`, `budget`
- `employees.csv` — columns: `id`, `name`, `position`, `skills`, `years_of_service`, `department_id`
- `projects.csv` — columns: `name`, `status`, `member_ids`, `deadline`, `department_id`

**Schema** (at `/app/schema.json`):
- JSON Schema draft-07 defining the output structure

**Output** (at `/app/organization.json`):
- JSON document conforming to the schema

## Execution

Run the generator script:
```bash
python3 /skill/scripts/generate.py
```

The script reads from `/app/data/*.csv` and writes to `/app/organization.json`.

**Note**: The skill package is mounted at `/skill/` inside the task container. The script path is `/skill/scripts/generate.py` relative to the container root.

## Core Mechanism

### 1. Data Ingestion
Read three CSV files using `csv.DictReader`. Strip whitespace from all field
names and values during ingestion.

### 2. Relationship Assembly
Build nested structure by:
- Creating an employee lookup table keyed by employee ID
- Grouping employees by `department_id`
- Grouping projects by `department_id`
- For each department, attaching its employees and projects as nested arrays

### 3. Field Normalization

**Semicolon-delimited fields** (`skills`, `member_ids`):
- Split on `;`
- Strip whitespace from each element
- Filter out empty strings (handles `""`, `"A;;B"`, `" "`)
- Return empty array for empty/null input

**Type conversions**:
- `budget` → float (from string, with robust parsing)
- `years_of_service` → int (from string, with robust parsing)
- `member_ids` → array of employee ID strings (preserved as-is, NOT resolved to names)

**Robust numeric parsing** (`parse_numeric` function):
The script uses a dedicated `parse_numeric(value, as_int=False)` function that handles:
- **Commas in numbers**: `"1,500,000"` → `1500000.0` (removes commas before parsing)
- **Float strings for integer fields**: `"10.5"` → `10` (converts to float first, then to int, which truncates)
- **Whitespace**: `" 1500000 "` → `1500000.0` (strips before parsing)
- **Mixed formatting**: `"1,500,000.50"` → `1500000.5` (handles commas and decimals together)
- **Empty/invalid values**: `""` or `None` → `0` or `0.0` (graceful fallback)

This robustness is critical for the **field_parsing_and_normalization** axis, which specifies that variants may include "numeric strings with different formatting" and "other value-level irregularities".

**Member ID handling (CRITICAL)**:
- The `member_ids` column in projects.csv contains employee IDs (e.g., `D001-E001`)
- The output `members` field must contain these same employee ID strings
- **Do NOT resolve IDs to employee names** — the tests verify that `members` values are a subset of `employee["id"]` values within each department
- The schema only requires `members` to be an array of strings; it does not specify names vs IDs
- Preserve the raw ID strings from the CSV after splitting and stripping whitespace

### 4. Statistics Computation

All statistics are computed over the **assembled nested structure** (not raw CSV):

| Statistic | Formula |
|---|---|
| `averageDepartmentBudget` | `sum(dept.budget for dept in departments) / len(departments)` |
| `totalEmployees` | `sum(len(dept.employees) for dept in departments)` |
| `skillDistribution` | Frequency count of each skill across all employees |
| `departmentSizes` | Employee count per department, keyed by department name |
| `projectStatusDistribution` | Frequency count of each project status across all projects |
| `averageYearsOfService` | `sum(emp.years_of_service for emp in all_employees) / total_employees` |

### 5. Metadata

The `metadata` object contains:
- `version`: String identifier (e.g., `"1.0"`)
- `timestamp`: ISO 8601 datetime string (UTC)
- `generator`: String identifier (e.g., `"organization-json-generator"`)

### 6. Organization-Level Fields

The schema requires `organization.name` and `organization.founded`, which are
**not present in any CSV file**. These must be provided as defaults:
- `name`: `"Organization"` (generic placeholder)
- `founded`: `"2024-01-01"` (valid ISO date)

**Note**: If tests expect specific values for these fields, they may need to be
adjusted. The task instruction says "without inventing placeholder entries" but
these fields are required by the schema and absent from source data, so some
default is necessary.

## Edge Cases & Robustness

### Entity Relationship Complexity (spec axis)
- **Departments with no projects**: Include with empty `projects: []` array
- **Departments with many employees/projects**: Handle arbitrary counts
- **Projects with empty member lists**: Parse empty `member_ids` → `members: []`
- **Dense project-member reuse**: Preserve member IDs as-is; tests verify they match employee IDs within the department
- **Cross-department references**: Member IDs in projects reference employees; they should remain as ID strings in the output

### Field Parsing & Normalization (spec axis)
- **Extra whitespace**: Strip all string values on read
- **Repeated delimiters**: `"A;;B"` → `["A", "B"]` (filter empties)
- **Empty multi-value fields**: `""` → `[]` (empty array)
- **Quoted text**: Handled by `csv.DictReader`
- **Numeric formatting**: Parse budget as float, years_of_service as int
- **Leading/trailing whitespace in IDs**: Strip before lookup

### Value Distribution for Aggregation (spec axis)
- **Skewed numeric values**: Floating-point division handles any range
- **Dominant/rare skills**: Count frequencies without distributional assumptions
- **Concentrated project statuses**: Count all status values present
- **Extreme numeric ranges**: Python handles arbitrary-precision integers and floats
- **Zero-employee departments**: Guard against division by zero in averages

## Critical Learnings & Common Pitfalls

### 1. Members Field: Preserve IDs, Do NOT Resolve to Names
**This is the most common mistake.** The `member_ids` column in projects.csv contains employee IDs (e.g., `D001-E001`). The output `members` field must contain these same ID strings, **not** resolved employee names.

**Why this matters:**
- Tests verify that `project["members"]` values are a subset of `employee["id"]` values within each department
- The schema only requires `members` to be an array of strings; it does not specify names vs IDs
- Resolving IDs to names will cause test failures even though the output validates against the schema

**Correct approach:**
```python
# Parse member_ids and preserve as-is
member_ids = parse_semicolon_list(proj['member_ids'])
proj_record = {
    "name": proj['name'].strip(),
    "status": proj['status'].strip(),
    "members": member_ids,  # IDs, not names!
    "deadline": proj['deadline'].strip()
}
```

**Incorrect approach (DO NOT DO THIS):**
```python
# WRONG: Resolving IDs to names
member_names = [emp_by_id[mid]['name'] for mid in member_ids]
```

### 2. Empty Collections Are Valid
- Departments with no projects: Include with `projects: []`
- Projects with no members: Include with `members: []`
- Do not skip or omit empty collections

### 3. Statistics Are Computed Over Assembled Data
All statistics should be computed from the final nested structure, not directly from CSV, to ensure consistency with the output data.

### 4. Budget Type: Float is Acceptable
The schema specifies `"type": "number"` for budget. Both `1500000.0` (float) and `1500000` (int) are valid and compare as equal in Python. Using `float()` is safe.

### 5. Numeric Parsing Must Be Robust
CSV data may contain numeric values with various formatting:
- **Commas**: `"1,500,000"` is common in financial data
- **Float strings for integer fields**: `"10.5"` or `"10.0"` for years_of_service
- **Whitespace**: Leading/trailing spaces around numbers

**Do NOT use simple `int()` or `float()` conversions.** Instead, use a robust parsing function that:
1. Strips whitespace
2. Removes commas
3. Converts to float first
4. Then converts to int if needed (truncates toward zero)
5. Handles empty/invalid values gracefully

**Example:**
```python
def parse_numeric(value, as_int=False):
    if not value:
        return 0 if as_int else 0.0
    cleaned = value.strip().replace(',', '')
    if not cleaned:
        return 0 if as_int else 0.0
    try:
        num = float(cleaned)
        return int(num) if as_int else num
    except ValueError:
        return 0 if as_int else 0.0
```

This prevents crashes on malformed data and ensures consistent behavior across variants with different numeric formatting conventions.

## Validation

After generation, validate output against the schema:
```python
import json, jsonschema
with open('/app/schema.json') as f:
    schema = json.load(f)
with open('/app/organization.json') as f:
    data = json.load(f)
jsonschema.validate(data, schema)
```

Key schema constraints to satisfy:
- `departments` array: `minItems: 3`
- `employees` array per department: `minItems: 2`
- `skills` array per employee: `minItems: 1`
- `budget`: `minimum: 0`
- `years_of_service`: `minimum: 0`, type `integer`
- `status`: enum `["Planning", "In Progress", "Testing", "Completed", "On Hold"]`
- Date formats: `date-time` for timestamp, `date` for founded and deadlines

## Implementation Reference

The authoritative implementation is at:
```
skill/organization-json-generator/scripts/generate.py
```

This script:
1. Reads all three CSV files
2. Builds lookup and grouping structures
3. Assembles the nested department/employee/project hierarchy
4. Computes all six required statistics
5. Generates metadata with current UTC timestamp
6. Writes validated JSON to `/app/organization.json`
