---
name: organization-json-generator
description: Transform CSV data (departments, employees, projects) into nested organization JSON with metadata and statistics, handling edge cases and schema validation
---

# Organization JSON Generator

## Purpose

This skill transforms three CSV source files into a single nested JSON document representing an organization's structure, including departments, employees, projects, and aggregate statistics. The output must validate against a provided JSON schema.

## Data Model

### Input: Three CSV Sources

1. **departments.csv**: Department records
   - Fields: `id`, `name`, `budget`
   - Each row represents one department

2. **employees.csv**: Employee records with department assignment
   - Fields: `id`, `name`, `position`, `skills`, `years_of_service`, `department_id`
   - `skills` is semicolon-delimited (e.g., "Python;Leadership;Project Management")
   - `department_id` links employee to department

3. **projects.csv**: Project records with department assignment
   - Fields: `name`, `status`, `member_ids`, `deadline`, `department_id`
   - `member_ids` is semicolon-delimited list of employee IDs
   - `status` must be one of: Planning, In Progress, Testing, Completed, On Hold
   - `department_id` links project to department

### Output: Nested JSON Structure

```
{
  "metadata": {
    "version": string,
    "timestamp": ISO-8601 date-time,
    "generator": string
  },
  "organization": {
    "name": string,
    "founded": ISO-8601 date,
    "departments": [
      {
        "id": string,
        "name": string,
        "budget": number (>= 0),
        "employees": [
          {
            "id": string,
            "name": string,
            "position": string,
            "skills": [string],
            "years_of_service": integer (>= 0)
          }
        ],
        "projects": [
          {
            "name": string,
            "status": enum,
            "members": [string],
            "deadline": ISO-8601 date
          }
        ]
      }
    ]
  },
  "statistics": {
    "averageDepartmentBudget": number,
    "totalEmployees": integer,
    "skillDistribution": {skill_name: count},
    "departmentSizes": {dept_name: employee_count},
    "projectStatusDistribution": {status: count},
    "averageYearsOfService": number
  }
}
```

## Processing Pipeline

### Step 1: Parse CSVs with Robust Normalization

- Read each CSV file using a CSV parser (e.g., Python's `csv.DictReader`)
- Strip whitespace from all field keys and values
- Handle quoted text and embedded commas gracefully

### Step 2: Normalize Field Values

**Semicolon-delimited fields** (skills, member_ids):
- Split on `;` delimiter
- Strip whitespace from each element
- Filter out empty strings (handles `""`, `";"`, `"a;;b"`)
- Result: `["a", "b"]` not `["a", "", "b"]` or `[""]`

**Numeric fields** (budget, years_of_service):
- Strip whitespace
- Remove thousands separators (commas)
- Parse as appropriate type (float for budget, int for years_of_service)
- Default to 0 if empty or unparseable

**Date fields** (deadline, founded):
- Preserve ISO-8601 format (YYYY-MM-DD)
- Strip whitespace

### Step 3: Build Lookup Structures

Create dictionaries for efficient grouping:
- `departments_by_id`: Map department ID → department record
- Initialize each department with empty `employees` and `projects` arrays

### Step 4: Group Related Entities

**Employees by department:**
- Iterate employees.csv
- For each employee, find their department by `department_id`
- Parse skills field into array
- Parse years_of_service as integer
- Append to department's `employees` array

**Projects by department:**
- Iterate projects.csv
- For each project, find its department by `department_id`
- Parse member_ids field into array (may be empty)
- Append to department's `projects` array

### Step 5: Assemble Nested JSON

Build the final structure:
- **metadata**: Use reasonable defaults
  - `version`: "1.0"
  - `timestamp`: Current UTC time in ISO-8601 format
  - `generator`: "csv-to-json-processor" or similar
- **organization**: 
  - `name`: "Organization" (or derive from context if available)
  - `founded`: "2020-01-01" (or derive from context if available)
  - `departments`: Array of department records in CSV order
- **statistics**: Compute over assembled data (see Step 6)

### Step 6: Compute Statistics

Compute all statistics over the **assembled data structure**, not raw CSV:

**averageDepartmentBudget:**
- Sum all department budgets
- Divide by number of departments
- Handle zero departments (return 0.0)

**totalEmployees:**
- Count all employees across all departments

**skillDistribution:**
- For each employee, for each skill in their skills array, increment count
- Result: `{skill_name: occurrence_count}`

**departmentSizes:**
- For each department, count employees
- Result: `{department_name: employee_count}`

**projectStatusDistribution:**
- For each project, count by status
- Include projects with empty member lists
- Result: `{status: count}`

**averageYearsOfService:**
- Sum all employees' years_of_service
- Divide by total number of employees
- Handle zero employees (return 0.0)

**Critical:** Use exact arithmetic, don't round intermediate results. Count all entities globally, not per-department then average the averages.

### Step 7: Validate and Write Output

- Validate output against JSON schema using `jsonschema` library
- Write validated JSON to output file with proper formatting (indent=2)

## Edge Case Handling

### Empty Multi-Value Fields

**Problem:** Empty semicolon-delimited field (e.g., `member_ids=""`)
- Naive: `"".split(";")` → `[""]` (incorrect)
- Correct: Filter empty strings → `[]`

**Solution:**
```python
def parse_semicolon_field(value):
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(";") if item.strip()]
```

### Departments Without Projects

**Problem:** Department exists in departments.csv but has no rows in projects.csv
- Must still appear in output with `"projects": []`

**Solution:** Initialize all departments with empty arrays before grouping projects.

### Departments Without Employees

**Problem:** Department exists but has no employees (schema may require minItems)
- Include department with `"employees": []`
- Note: Schema may have `minItems: 2` for employees, but this is a seed constraint

**Solution:** Same as above - initialize with empty arrays.

### Projects With Empty Member Lists

**Problem:** Project has `member_ids=""` or `member_ids=";;"`
- Must produce `"members": []` not `[""]`

**Solution:** Use the robust semicolon parser that filters empties.

### Cross-Department Member References

**Problem:** Project members are listed by employee ID but may reference employees from other departments
- The member_ids in output should reflect exactly what the CSV says
- Do not filter or validate cross-department membership

**Solution:** Store member_ids as-is after parsing (just split and strip).

### Skewed Numeric Distributions

**Problem:** Family variants may have highly skewed budgets or years-of-service values
- Same statistics formula applies regardless of distribution
- Avoid division by zero

**Solution:** 
- Check for zero counts before dividing
- Use exact arithmetic (don't round intermediate results)
- Count all entities globally

### Extra Whitespace and Formatting

**Problem:** CSV fields may have extra whitespace, repeated delimiters, quoted text
- `" Python ; Leadership "` → `["Python", "Leadership"]`
- `"a;;b"` → `["a", "b"]`
- `"1,500,000"` → `1500000.0`

**Solution:** Strip all values, filter empty splits, remove thousands separators.

## Family Variation Axes

This skill handles three variation dimensions:

### 1. Entity Relationship Complexity

**Seed:** 3 employees per department, 1-2 projects per department, light overlap
**Family variants may include:**
- Departments with no projects (must output `"projects": []`)
- Departments with many more projects or employees
- Projects with empty member lists (must output `"members": []`)
- Denser project-member reuse patterns

**Handling:** The grouping logic is relationship-agnostic. Empty arrays are initialized for all departments before grouping, so missing relationships produce empty arrays naturally.

### 2. Field Parsing and Normalization

**Seed:** Direct string fields, numeric budgets, semicolon-delimited skills/members, ISO dates
**Family variants may include:**
- Extra whitespace in fields
- Repeated delimiters (`"a;;b"`)
- Empty multi-value fields
- Quoted text with embedded delimiters
- Numeric strings with different formatting (`"1,500,000"`)

**Handling:** Robust normalization at parse time:
- Strip all whitespace
- Filter empty splits
- Remove thousands separators
- Handle quoted text via CSV parser

### 3. Value Distribution for Aggregation

**Seed:** Small, balanced dataset with modest numeric ranges
**Family variants may include:**
- Highly skewed budgets or years-of-service
- Dominant or rare skills
- Heavily concentrated project statuses
- Extreme numeric ranges

**Handling:** Statistics computation is distribution-agnostic:
- Use exact arithmetic
- Count all entities globally
- Handle zero counts to avoid division by zero
- Same formulas apply regardless of distribution

## Implementation Notes

### Script Location

The script should be placed in the skill directory and executed from the task environment:
```bash
python3 /skill/generate.py
```

Or copy to /app and run:
```bash
cp /skill/generate.py /app/generate.py
python3 /app/generate.py
```

### Environment Variables

The script accepts environment variables for flexibility:
- `DATA_DIR`: Directory containing CSV files (default: `/app/data`)
- `SCHEMA_PATH`: Path to JSON schema (default: `/app/schema.json`)
- `OUTPUT_PATH`: Path for output JSON (default: `/app/organization.json`)

### Validation

The script validates output against the schema using the `jsonschema` library. If validation fails, the script exits with error code 1 and prints the validation error to stderr.

### Organization Metadata

The `organization.name` and `organization.founded` fields are not present in the CSV sources. The script uses sensible defaults:
- `name`: "Organization"
- `founded`: "2020-01-01"

If the task provides these values through other means (e.g., a config file or environment variables), the script should be modified to read them.

## Testing Checklist

When validating the solution, verify:

- [ ] Output validates against JSON schema
- [ ] All departments from CSV appear in output (including those with no projects)
- [ ] Empty member lists produce `[]` not `[""]`
- [ ] Semicolon-delimited fields are properly parsed (no empty strings)
- [ ] Statistics are computed over assembled data, not raw CSV
- [ ] Division by zero is handled (zero employees, zero departments)
- [ ] Numeric fields are properly typed (budget as number, years_of_service as integer)
- [ ] Date fields are in ISO-8601 format
- [ ] Project status values match the enum in schema

## Example Usage

```python
# In the task environment
import subprocess
import sys

# Run the generator
result = subprocess.run(
    [sys.executable, "/skill/generate.py"],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print(f"Error: {result.stderr}")
    sys.exit(1)

print("Success: /app/organization.json created")
```

## Reusability

This skill is designed to work across the full family of organization-json-generator tasks. The processing pipeline is:
- **Data-source agnostic**: Works with any CSV files following the same schema
- **Relationship-agnostic**: Handles any cardinality of department-employee-project relationships
- **Distribution-agnostic**: Statistics formulas work for any value distribution
- **Edge-case robust**: Handles empty fields, missing relationships, formatting irregularities

The only assumption is that the input CSVs follow the field structure described in the Data Model section.
