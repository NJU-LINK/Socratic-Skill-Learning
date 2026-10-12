---
name: organization-json-generator
description: >
  Transforms multiple CSV files (departments, employees, projects) into a
  single nested organization JSON document conforming to a provided JSON schema.
  Handles three-way joins via department_id, defensive field parsing
  (semicolon-delimited lists, whitespace, numeric coercion), edge cases
  (departments with no projects, empty member lists), and aggregate statistics
  computation.
---

# Organization JSON Generator

## Task Pattern

Given:
- Three CSV input files: `departments.csv`, `employees.csv`, `projects.csv` in `/app/data/`
- A JSON schema at `/app/schema.json`

Produce:
- A single `/app/organization.json` that validates against the schema

**Schema-first approach**: Always read `/app/schema.json` first to understand the required output structure. The schema defines required fields, types, enums, and constraints. Your implementation must produce output that validates against whatever schema is provided, not just the v01 schema.

## Architecture: Three-Way Join via department_id

The data model is a nested tree:

```
organization
├── metadata (generated, not from CSV)
├── organization
│   ├── name, founded (fixed/generated)
│   └── departments[]
│       ├── id, name, budget (from departments.csv)
│       ├── employees[] (from employees.csv, joined by department_id)
│       │   ├── id, name, position (direct string fields)
│       │   ├── skills (semicolon-delimited → array)
│       │   └── years_of_service (string → integer)
│       └── projects[] (from projects.csv, joined by department_id)
│           ├── name, status, deadline (direct string fields)
│           └── members (semicolon-delimited member_ids → array)
└── statistics (computed aggregates)
```

**Join keys:**
- `employees.department_id` → groups employees under their department
- `projects.department_id` → groups projects under their department
- `projects.member_ids` → semicolon-delimited employee IDs (emitted as string array; no resolution to employee objects needed)

## Field Parsing Rules

### Defensive Parsing (handles family-axis variations)

1. **Whitespace stripping**: Strip every CSV field value after reading. Use Python's `csv.DictReader` which handles quoted text correctly.

2. **Semicolon-delimited lists** (skills, member_ids):
   ```python
   def parse_semicolon_list(value):
       if not value:
           return []
       return [s.strip() for s in value.split(';') if s.strip()]
   ```
   This handles: extra whitespace, repeated delimiters (`;;`), empty fields, trailing delimiters.

3. **Numeric fields**:
   - `budget` (department): `float(value.strip().replace(',', ''))` — convert to int if whole number
   - `years_of_service` (employee): `int(value.strip())`

4. **Status values**: Must match the schema enum exactly: `"Planning"`, `"In Progress"`, `"Testing"`, `"Completed"`, `"On Hold"`. Preserve the original case from CSV.

5. **Dates**: Preserve as-is (ISO format `YYYY-MM-DD`).

## Edge Cases

| Situation | Required Handling |
|-----------|-------------------|
| Department with no projects | `projects: []` (empty array, key must be present) |
| Project with empty member_ids | `members: []` (not `[""]`) |
| Employee with empty skills | Schema requires `minItems: 1` — if this occurs, data is invalid |
| Extra whitespace in fields | Strip before processing |
| Repeated delimiters (`;;`) | Filter empty strings after split |

## Statistics Computation

All statistics are computed from the assembled department objects:

| Statistic | Definition |
|-----------|------------|
| `averageDepartmentBudget` | `sum(all department budgets) / count(departments)` |
| `totalEmployees` | Total count of employee rows across all departments |
| `skillDistribution` | Global counter: for each skill in each employee's skills list, increment count. Keys = skill names, values = counts |
| `departmentSizes` | Per-department employee count. **Keyed by department name** |
| `projectStatusDistribution` | Count projects by status across all departments |
| `averageYearsOfService` | `sum(all employees' years_of_service) / total_employees` |

## Metadata

The `metadata` block is generated, not derived from CSV:
- `version`: Fixed string (e.g., `"1.0"`)
- `timestamp`: ISO 8601 datetime (e.g., `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`)
- `generator`: Any descriptive string (e.g., `"organization-json-generator"`)

The `organization.name` and `organization.founded` are also not from CSV — use reasonable defaults.

## Implementation

The script is at `scripts/generate.py`. It uses only Python standard library (`csv`, `json`, `datetime`, `os`).

### Deployment and Invocation

The skill's `scripts/generate.py` lives in the skill package on the host workspace. It is **not** directly accessible inside the `/app` container via filesystem copy. The solver must:

1. **Read** `scripts/generate.py` from the skill package using the `read` tool (host workspace path)
2. **Write** its contents to `/app/generate.py` using `task_shell` with a heredoc (e.g., `cat > /app/generate.py << 'PYEOF' ... PYEOF`)
3. **Run** `python3 /app/generate.py` inside the container
4. **Validate** the output against the schema

The script accepts optional positional arguments: `python3 /app/generate.py [data_dir] [schema_path] [output_path]` with defaults `/app/data`, `/app/schema.json`, `/app/organization.json`.

### Validation

After generation, always validate:
```python
import json, jsonschema
schema = json.load(open('/app/schema.json'))
data = json.load(open('/app/organization.json'))
jsonschema.validate(data, schema)
```

## Family-Axis Considerations

This skill handles variation along three axes:

1. **Entity relationship complexity**: Departments with 0 or many projects, varying employee counts per department, dense or sparse project-member overlap. The join logic handles all cases — empty arrays for missing relationships, no hard-coded counts.

2. **Field parsing and normalization**: Extra whitespace, repeated delimiters, empty multi-value fields, quoted text, differently formatted numbers. All handled by defensive parsing functions.

3. **Value distribution for aggregation**: Skewed budgets/years, dominant/rare skills, concentrated statuses. The statistics computation uses the same formulas regardless of distribution — no special-casing needed.
