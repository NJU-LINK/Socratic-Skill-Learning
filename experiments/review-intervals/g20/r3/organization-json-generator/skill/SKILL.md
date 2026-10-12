---
name: organization-json-generator
description: Transform CSV data (departments, employees, projects) into nested JSON with metadata, organization structure, and aggregate statistics. Handles relationship mapping, field normalization, and schema validation.
---

# Organization JSON Generator

## Quick Start

**Run the included script to solve the task:**

```bash
python3 /skill/scripts/generate_org_json.py
```

This single command:
- Reads CSV files from `/app/data/` (departments.csv, employees.csv, projects.csv)
- Transforms them into nested JSON structure
- Validates against `/app/schema.json`
- Writes schema-valid output to `/app/organization.json`

**That's it. The script handles everything.**

## What the Script Does

The script performs three main operations:

1. **Parses and normalizes CSV data**
   - Handles semicolon-delimited lists (skills, member_ids)
   - Normalizes numeric fields (commas, currency symbols, float-to-int)
   - Strips whitespace from all fields
   - Provides clear error messages for missing files or columns

2. **Builds nested organization structure**
   - Groups employees by department_id
   - Groups projects by department_id
   - Preserves all relationships exactly

3. **Computes statistics**
   - averageDepartmentBudget, totalEmployees
   - skillDistribution, departmentSizes (keyed by name)
   - projectStatusDistribution, averageYearsOfService

## Edge Cases Handled

✓ Departments with no projects → empty `projects: []` array  
✓ Projects with no members → empty `members: []` array  
✓ Repeated delimiters: `"Python;;JS"` → `["Python", "JS"]`  
✓ Extra whitespace: all fields stripped  
✓ Numeric formatting: `"1,500,000"` → `1500000.0`, `"10.0"` → `10`  
✓ Empty multi-value fields → empty arrays  
✓ Missing files or columns → clear error messages  
✓ Invalid numeric values → descriptive errors  

## Custom Paths (if needed)

```bash
python3 /skill/scripts/generate_org_json.py /path/to/data /path/to/output.json
```

## Verification

After running the script, verify the output:

```bash
python3 -c "
import json, jsonschema
with open('/app/schema.json') as f: schema = json.load(f)
with open('/app/organization.json') as f: data = json.load(f)
jsonschema.validate(instance=data, schema=schema)
print('✓ Valid')
"
```

## Technical Details

### Input Format

Three CSV files with these columns:

**departments.csv**: `id, name, budget`  
**employees.csv**: `id, name, position, skills, years_of_service, department_id`  
**projects.csv**: `name, status, member_ids, deadline, department_id`

### Output Schema

JSON with three top-level sections:

- **metadata**: version, timestamp, generator
- **organization**: name, founded, departments array (each with employees and projects)
- **statistics**: 6 aggregate metrics

### Key Implementation Points

- `departmentSizes` uses department **names** as keys (not IDs)
- `skills` and `members` are arrays (parsed from semicolon-delimited strings)
- All numeric fields are properly typed (budget as float, years_of_service as int)
- Empty relationships produce empty arrays, not null
- Robust error handling with clear messages for debugging

### Requirements

- Python 3.6+ with standard library only
- No external dependencies
