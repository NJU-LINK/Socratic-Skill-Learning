---
name: organization-json-generator
description: >
  Transforms CSV data describing an organization's departments, employees, and
  projects into a nested, schema-conformant JSON file. Handles three-stage
  pipeline: CSV parsing with dynamic column detection and robust field
  normalization, relationship assembly via foreign-key grouping, and aggregate
  statistics computation. Generalizes across varying entity relationship
  complexity, field parsing irregularities, and value distribution patterns.
---

# Organization JSON Generator

## Purpose

Transform three CSV files (`departments.csv`, `employees.csv`, `projects.csv`)
into a single nested JSON file (`organization.json`) that validates against a
provided JSON schema. The output includes organization metadata, department
records with their nested employees and projects, and aggregate statistics.

## Quick Start (for solver agents)

**This skill includes a tested Python script. Use it directly — do NOT re-implement from scratch.**

The script at `scripts/generate.py` has been tested against:
- v01 data (6/6 tests passed)
- BOM-encoded CSV files
- Alternate column names (e.g., `member_ids` vs `members`, `department_id` vs `dept_id`)
- Edge cases: empty members, departments with no projects, whitespace/delimiter variations
- Missing required columns (fails loudly with diagnostic message)

**Steps to solve:**
1. The skill package is mounted at `/skill` inside the task container
2. Copy the script: `cp /skill/scripts/generate.py /app/generate.py`
3. Run it: `python3 /app/generate.py`
4. The script reads CSVs from `/app/data/`, writes JSON to `/app/organization.json`, and auto-validates against `/app/schema.json`

The script handles all edge cases documented below. Re-implementing from this documentation risks missing subtle details like BOM encoding (`utf-8-sig`), None-key filtering, or exact column alias matching.

## Architecture: Three-Stage Pipeline

```
CSV Parsing (with column detection) → Relationship Assembly → Statistics + JSON Output
```

### Stage 1: CSV Parsing with Dynamic Column Detection + Normalization

Read each CSV using Python's `csv.DictReader` with `encoding='utf-8-sig'` to
handle BOM (Byte Order Mark) if present. Before parsing rows, detect actual
column names from headers and map them to canonical field names.

#### Dynamic Column Detection

Family variants may use different CSV header names for the same logical field
(e.g., `member_ids` vs `members`, `department_id` vs `dept_id`, `years_of_service`
vs `tenure`). The script maintains an alias table for each expected field and
matches headers case-insensitively with underscore normalization.

**Alias table (canonical → alternatives):**

| CSV Type | Canonical Field | Aliases |
|---|---|---|
| departments | id | id, department_id, dept_id |
| departments | name | name, department_name, dept_name |
| departments | budget | budget, dept_budget, annual_budget |
| employees | id | id, employee_id, emp_id |
| employees | name | name, employee_name, emp_name, full_name |
| employees | position | position, role, title, job_title |
| employees | skills | skills, skill_set, competencies |
| employees | years_of_service | years_of_service, years, yos, tenure, experience_years |
| employees | department_id | department_id, dept_id, department, dept |
| projects | name | name, project_name |
| projects | status | status, project_status, state |
| projects | member_ids | member_ids, members, employee_ids, team_members |
| projects | deadline | deadline, due_date, end_date, target_date |
| projects | department_id | department_id, dept_id, department, dept |

**Loud failure on missing columns:** If a required column cannot be matched
to any alias, the script raises a `ValueError` with the missing field name,
available columns, and expected aliases. This prevents silent data loss.

#### Normalization Rules

| Field Type | Normalization |
|---|---|
| **String** | `.strip()`, remove residual quotes |
| **Semicolon-delimited list** (skills, member_ids) | `split(';')`, strip each item, filter empty strings. Handles `;;`, ` ; ; `, trailing semicolons |
| **Integer** (years_of_service) | Strip whitespace, remove commas, `int(float(cleaned))` to handle "10.0" style |
| **Number** (budget) | Strip whitespace, remove commas, `float()` or `int()` based on decimal presence |
| **Date** | Keep as ISO `YYYY-MM-DD` string; parse alternate formats if needed |
| **Empty multi-value fields** | Result in `[]` (empty list) |
| **Encoding** | UTF-8 with BOM support via `utf-8-sig`; None values from short CSV rows become empty strings |

#### Key Implementation Detail

```python
def parse_list_field(value):
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(';') if item.strip()]
```

This handles all delimiter irregularities: extra whitespace, repeated
delimiters, empty fields, and trailing delimiters.

### Stage 2: Relationship Assembly

Build a nested structure by grouping employees and projects under their
respective departments using foreign-key columns.

#### Assembly Algorithm

1. Create a department map keyed by department `id`, preserving insertion order
2. Each department entry starts with empty `employees: []` and `projects: []`
3. Iterate employees: append to `dept_map[employee.department_id].employees`
4. Iterate projects: append to `dept_map[project.department_id].projects`
5. Output departments in original CSV order

#### Edge Cases

- **Departments with no projects**: `projects` array is `[]` — do NOT invent placeholders
- **Projects with empty member lists**: `members` array is `[]` — do NOT invent placeholders
- **Dense project-member reuse**: Multiple projects may share members; parse each project's members independently
- **Orphan employees/projects** (FK doesn't match any department): Skip silently

### Stage 3: Statistics Computation + JSON Output

Walk the assembled structure to compute all required aggregate statistics.

#### Required Statistics

| Statistic | Computation |
|---|---|
| `averageDepartmentBudget` | `sum(dept.budget for all depts) / count(depts)` |
| `totalEmployees` | Sum of employee counts across all departments |
| `skillDistribution` | `{skill_name: count}` — count how many employees have each skill, across ALL departments |
| `departmentSizes` | `{dept_name: employee_count}` for each department |
| `projectStatusDistribution` | `{status: count}` — count projects per status across ALL departments |
| `averageYearsOfService` | `sum(emp.years_of_service for all emps) / count(all_emps)` |

#### Robustness

- Guard against division by zero (0 departments, 0 employees)
- Iterate across ALL departments for global statistics (skill distribution, project status)
- Use `defaultdict(int)` for frequency counting

### Metadata Block

The schema requires an organization-level metadata block:

```json
{
  "metadata": {
    "version": "1.0",
    "timestamp": "<ISO 8601 date-time>",
    "generator": "organization-json-generator"
  }
}
```

The `organization.name` and `organization.founded` fields are required by the
schema but not present in the CSV data. Use `"Organization"` for name and
derive `founded` from the earliest date found in project deadlines (fall back
to `"2020-01-01"` if no dates exist).

## Schema Conformance Checklist

- `metadata.version`: string ✓
- `metadata.timestamp`: ISO 8601 date-time string ✓
- `metadata.generator`: string ✓
- `organization.name`: string ✓
- `organization.founded`: date string (YYYY-MM-DD) ✓
- `organization.departments`: array, minItems 3 ✓
- Each department: `id` (string), `name` (string), `budget` (number ≥ 0), `employees` (array, minItems 2), `projects` (array) ✓
- Each employee: `id` (string), `name` (string), `position` (string), `skills` (array of strings, minItems 1), `years_of_service` (integer ≥ 0) ✓
- Each project: `name` (string), `status` (enum: Planning/In Progress/Testing/Completed/On Hold), `members` (array of strings), `deadline` (date string) ✓
- Statistics: all six required fields present with correct types ✓

## Running

```bash
python3 scripts/generate.py [data_dir] [output_path] [schema_path]
# Defaults: data_dir=/app/data, output_path=/app/organization.json
# Schema auto-detected at /app/schema.json if not specified
```

The script auto-detects the schema at `/app/schema.json` and validates the
output against it. If validation fails, the script raises an error with
details about the schema violation.

## Validation

After generation, validate against the schema:

```python
import json, jsonschema
with open('organization.json') as f: data = json.load(f)
with open('schema.json') as f: schema = json.load(f)
jsonschema.validate(data, schema)
```

## Family Variation Handling

### Axis 1: Entity Relationship Complexity
- The assembly algorithm works for any number of departments, employees per department, and projects per department
- Departments with no projects get empty `projects: []`
- Projects with empty member lists get empty `members: []`
- Dense member reuse across projects is handled naturally (each project parsed independently)

### Axis 2: Field Parsing and Normalization
- All string fields are stripped of whitespace
- Semicolon-delimited fields handle repeated delimiters, extra whitespace, empty segments
- Numeric fields handle commas, whitespace, and decimal formatting
- Date fields are normalized to ISO format
- Column names are dynamically detected from headers with alias matching

### Axis 3: Value Distribution for Aggregation
- Statistics computation uses the same formulas regardless of value distribution
- Division guards prevent errors with zero counts
- Frequency counting works for any distribution pattern (skewed, uniform, concentrated)
