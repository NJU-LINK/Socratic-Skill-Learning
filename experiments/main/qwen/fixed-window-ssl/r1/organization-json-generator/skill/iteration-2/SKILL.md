---
name: organization-json-generator
description: >
  Transform multiple related CSV files (departments, employees, projects) into a
  single nested JSON document that validates against a provided JSON schema.
  Handles cross-table relationship resolution, field normalization, and
  aggregate statistics computation. Robust to variations in entity relationship
  complexity, field formatting irregularities, and value distribution patterns.
---

# Organization JSON Generator

## When to Use

This skill applies when the task requires:
- Reading 2-3 CSV files representing related entities (departments, employees, projects)
- Assembling them into a nested JSON structure defined by a JSON schema
- Computing aggregate statistics over the assembled data
- Writing schema-valid JSON output

## Input/Output Contract

### Inputs (in `/app/data/`)
- `departments.csv`: id, name, budget (and possibly other fields)
- `employees.csv`: id, name, position, skills (semicolon-delimited), years_of_service, department_id
- `projects.csv`: name, status, member_ids (semicolon-delimited employee IDs), deadline, department_id

### Schema (`/app/schema.json`)
Defines the exact output structure. Always read and validate against it.

### Output (`/app/organization.json`)
A single JSON file with three top-level sections:
1. **metadata**: version, timestamp (ISO datetime), generator name
2. **organization**: name, founded (date), departments array (each with nested employees and projects)
3. **statistics**: aggregate metrics over the assembled data

## Core Methodology

### 1. Read and Normalize CSV Data
- Use `csv.DictReader` for robust parsing (handles quoted fields)
- Strip whitespace from all keys and values
- Handle empty/missing fields gracefully

### 2. Parse Multi-Value Fields
- Skills and member_ids are semicolon-delimited in the CSV
- Split by `;`, strip each item, filter empty strings
- Handle edge cases: empty fields, repeated delimiters, extra whitespace

### 3. Parse Numeric Fields
- **Preserve int vs float from source**: if no decimal point, parse as int; otherwise float
- Remove common formatting: commas, quotes
- This matters for exact equality comparisons in tests

### 4. Build Relationship Structure
- Create department objects indexed by department ID
- Attach employees to their department via `department_id`
- Attach projects to their department via `department_id`
- **Keep member_ids as employee IDs** (do NOT resolve to names; the `members` field contains the raw IDs from the CSV)
- Handle edge cases: departments with no projects (empty array), projects with no members (empty array)

### 5. Compute Statistics
Six required statistics:
- `averageDepartmentBudget`: sum of budgets / number of departments (float)
- `totalEmployees`: count of all employees (int)
- `skillDistribution`: dict mapping skill name → count of employees with that skill
- `departmentSizes`: dict mapping department name → employee count
- `projectStatusDistribution`: dict mapping status → count of projects with that status
- `averageYearsOfService`: sum of years / number of employees (float)

### 6. Handle Fields Not in CSV
- `organization.name` and `organization.founded` are required by schema but not in CSV
- Use reasonable defaults: `"Organization"` for name, `"2020-01-01"` for founded
- `metadata.timestamp`: use current ISO datetime
- `metadata.version`: use `"1.0.0"`
- `metadata.generator`: use script name

## Family Variation Handling

### Entity Relationship Complexity
- **Departments with no projects**: emit empty `projects` array
- **Departments with many employees/projects**: no special handling needed, just iterate
- **Projects with empty member lists**: emit empty `members` array
- **Dense member reuse**: resolve each member_id independently via lookup

### Field Parsing and Normalization
- **Extra whitespace**: strip all values after CSV read
- **Repeated delimiters**: filter empty strings after split
- **Empty multi-value fields**: return empty list
- **Quoted text**: handled by csv.DictReader
- **Numeric formatting**: remove commas and quotes before parsing
- **Different delimiters**: if not semicolon, detect from data or schema hints

### Value Distribution for Aggregation
- **Skewed budgets/years**: use float division for averages, no rounding unless schema requires
- **Dominant/rare skills**: count all occurrences, no filtering
- **Concentrated statuses**: count all, no filtering
- **Extreme numeric ranges**: preserve precision, use Python's native numeric types

## Validation Checklist

Before submitting output:
1. ✅ JSON parses without errors
2. ✅ Validates against schema.json (use jsonschema library)
3. ✅ All required fields present at every level
4. ✅ Type constraints satisfied (numbers are numbers, strings are strings, arrays are arrays)
5. ✅ Enum constraints satisfied (e.g., project status must be one of the allowed values)
6. ✅ Statistics computed correctly (spot-check a few values manually)
7. ✅ Relationships preserved exactly (no invented entries, no missing entries)

## Critical Lessons

### Don't Assume Semantic Transformation from Field Names
When the CSV has `member_ids` and the schema has `members`, **do not assume** you need to resolve IDs to names. The schema's `members` field accepts strings, and tests may expect the raw IDs. **Always check the test contract** — schema field names are hints, but tests are definitive.

**Evidence from v01:**
- CSV: `member_ids` = `D001-E001;D001-E002;D001-E003`
- Schema: `members: { type: array, items: { type: string } }`
- Test: `assert set(project["members"]).issubset(employee_ids)` where `employee_ids` are IDs
- **Correct behavior**: Keep member_ids as-is (employee IDs), don't resolve to names

### Preserve CSV Ordering
When tests do deep equality checks (`actual == expected`), ordering matters:
- Departments: iterate in CSV order
- Employees within departments: append in CSV order
- Projects within departments: append in CSV order

### Field Sets Must Match Exactly
Don't add extra fields or omit required ones. The schema defines the exact contract:
- Employee: `id`, `name`, `position`, `skills`, `years_of_service` (no more, no less)
- Project: `name`, `status`, `members`, `deadline` (no more, no less)
- Department: `id`, `name`, `budget`, `employees`, `projects` (no more, no less)

## Implementation Notes

- Use Python 3 with standard library (csv, json, collections, datetime)
- Validate output with `jsonschema` library if available
- Write output with `json.dump(indent=2)` for readability
- Add trailing newline for POSIX compliance
- The script should be idempotent: running it multiple times produces the same output (except timestamp)
