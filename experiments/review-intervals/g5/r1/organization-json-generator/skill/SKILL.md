---
name: organization-json-generator
description: >
  Transforms multi-table CSV data (departments, employees, projects) into a
  nested, schema-conformant organization JSON with metadata, hierarchical
  department records, and aggregate statistics. Handles varying entity
  relationship complexity, field normalization challenges, and diverse
  value distributions.
---

# Organization JSON Generator

## Environment Architecture

**Critical**: The skill authoring workspace and the task container are two separate filesystems.

- **Author workspace** (where you write files with the `write` tool): Your current working directory
  - Use **relative paths** with the `read` and `ls` tools: `skill/organization-json-generator/SKILL.md`
  - Do NOT use absolute paths with these tools
- **Task container** (where you execute commands with `task_shell`): `/app/`
  - Input CSVs: `/app/data/departments.csv`, `/app/data/employees.csv`, `/app/data/projects.csv`
  - JSON schema: `/app/schema.json`
  - Output: `/app/organization.json`
  - Skill package (read-only mount): `/skill/`
    - SKILL.md: `/skill/SKILL.md`
    - Script: `/skill/scripts/generate.py`

**Rule**: Use `task_shell` for ALL access to `/app/` and `/skill/` paths. The `read` and `ls` tools only work with relative paths in the author workspace.

## Quick Start

```bash
# Copy the script from the skill mount into the task container and run it
cp /skill/scripts/generate.py /app/generate.py
python3 /app/generate.py
```

That's it. The script handles everything: reading CSVs, normalizing fields, assembling the hierarchy, computing statistics, and validating against the schema.

## Task Family

Given CSV files describing an organization's departments, employees, and projects,
produce a single JSON file that:

1. Includes metadata (version, timestamp, generator)
2. Nests employees and projects under their parent departments
3. Computes aggregate statistics across the entire organization
4. Validates against a provided JSON schema

The three CSV inputs always share a `department_id` foreign-key pattern:
- `departments.csv` — id, name, budget (and possibly other columns)
- `employees.csv` — id, name, position, skills (semicolon-delimited), years_of_service, department_id
- `projects.csv` — name, status, member_ids (semicolon-delimited), deadline, department_id

The output JSON schema is always provided at `/app/schema.json` and defines the
exact structure, required fields, types, and constraints.

## Procedure

### 1. Read and inspect inputs (optional)

If you need to understand the data:

```bash
cat /app/data/departments.csv /app/data/employees.csv /app/data/projects.csv
cat /app/schema.json
```

Identify column names from the CSV headers. The linking column is always
`department_id` in employees and projects, matching `id` in departments.

### 2. Parse and normalize fields

**Semicolon-delimited lists** (skills, member_ids):
- Split on `;`
- Strip whitespace from each element
- Filter out empty strings (handles empty fields, repeated delimiters like `a;;b`)
- Result: clean array of non-empty strings

**Numeric fields** (budget, years_of_service):
- Strip whitespace
- Remove thousands separators (commas): `"1,500,000"` → `1500000`
- Parse budget as `float`, years_of_service as `int`
- Guard against empty/missing values → default to 0

**String fields**: strip leading/trailing whitespace from all values.

### 3. Assemble the hierarchy

- Create a department record for each row in departments.csv
- Group employees by `department_id` → attach to matching department's `employees` array
- Group projects by `department_id` → attach to matching department's `projects` array
- Preserve CSV row order for departments
- Departments with no matching projects get `"projects": []`
- Projects with empty member_ids get `"members": []`

### 4. Populate schema-required non-CSV fields

The schema requires fields that have no CSV source. Use sensible defaults:

| Field | Value |
|-------|-------|
| `metadata.version` | `"1.0"` |
| `metadata.timestamp` | Current UTC datetime in ISO 8601 (`%Y-%m-%dT%H:%M:%SZ`) |
| `metadata.generator` | `"organization-json-generator"` |
| `organization.name` | `"Organization"` |
| `organization.founded` | `"2020-01-01"` |

### 5. Compute statistics

All six statistics are always required:

| Statistic | Computation |
|-----------|-------------|
| `averageDepartmentBudget` | `sum(all department budgets) / count(departments)` |
| `totalEmployees` | Total count of employee records across all departments |
| `skillDistribution` | `{skill_name: count_of_employees_with_that_skill}` |
| `departmentSizes` | `{department_name: employee_count}` |
| `projectStatusDistribution` | `{status_value: count_of_projects_with_that_status}` |
| `averageYearsOfService` | `sum(all years_of_service) / totalEmployees` |

Guard against division by zero (0 departments → avg budget = 0.0, 0 employees → avg years = 0.0).

### 6. Write and validate

Write the JSON to `/app/organization.json`. Validate against the schema using
`jsonschema.validate()` if the library is available.

## Edge Cases and Robustness

### Entity relationship complexity
- Departments with zero projects → empty `projects: []` (schema has no `minItems` on projects)
- Projects with empty member lists → empty `members: []` (schema has no `minItems` on members)
- Departments with many employees or projects → no special handling needed
- Dense project-member reuse (same employee on many projects) → just list member_ids per project independently

### Field normalization
- Extra whitespace: `" Python ; Java "` → `["Python", "Java"]`
- Repeated delimiters: `"Python;;Java"` → `["Python", "Java"]`
- Empty multi-value field: `""` → `[]`
- Quoted CSV text: Python's `csv.DictReader` handles this natively
- Numeric formatting: `"1,500,000"` → `1500000.0`, `" 7 "` → `7`
- BOM in CSV files: use `utf-8-sig` encoding to handle optional BOM

### Value distribution for aggregation
- Highly skewed budgets or years: standard float arithmetic handles this
- Dominant or rare skills: simple counting works regardless of distribution
- Extreme numeric ranges: Python handles arbitrary-precision integers and floats

## Implementation

The reference implementation is at `/skill/scripts/generate.py` (read-only mount in task container).

To use it:

```bash
cp /skill/scripts/generate.py /app/generate.py
python3 /app/generate.py
```

The script accepts optional arguments:

```bash
python3 /app/generate.py --data-dir /app/data --schema /app/schema.json --output /app/organization.json
```

## Validation Checklist

After generating, verify:
- [ ] Output validates against `/app/schema.json`
- [ ] All departments from CSV are present with correct employees and projects
- [ ] Semicolon-delimited fields are properly split into arrays
- [ ] Numeric fields are numbers (not strings) in the JSON
- [ ] Statistics are computed correctly (spot-check a few values)
- [ ] Empty arrays where expected (no-project departments, no-member projects)
- [ ] Metadata fields are present and correctly typed
