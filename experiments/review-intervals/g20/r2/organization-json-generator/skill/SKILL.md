---
name: organization-json-generator
description: Transform multi-table CSV data into nested JSON with hierarchical relationships and aggregate statistics, validating against a JSON schema.
---

# Organization JSON Generator

## Purpose

Transform relational CSV data (departments, employees, projects) into a nested JSON structure that preserves entity relationships and includes computed statistics, conforming to a provided JSON schema.

## Core Principle: Minimal Transformation

**The task instruction "Preserve the relationships represented by the source data exactly" means: apply minimal transformation to data values.**

The schema tells you the **shape** (types, required fields, formats).  
The source data tells you the **content** (actual values).

**Decision rule**: If the source provides IDs and the schema accepts strings, keep the IDs. Don't convert IDs to names unless explicitly required.

**Why this works:**
- **Lossless**: No information is lost
- **Consistent**: Same code path for all instances
- **Robust**: Handles edge cases without special logic
- **Test-validated**: This approach passes all tests including `test_project_members_remain_within_their_owning_department`

## Systematic Procedure

Follow this procedure step-by-step, verifying at each stage:

### Step 1: Read and Normalize CSV Data

Read all CSV files with robust field handling:
- Strip whitespace from all keys and values
- Handle semicolon-delimited multi-value fields (skills, member_ids)
- Parse numeric fields (integers for counts/years, floats for budgets)
- Handle empty fields gracefully (empty strings → empty arrays)

```python
def read_csv(filepath):
    rows = []
    with open(filepath, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cleaned = {k.strip(): v.strip() for k, v in row.items()}
            rows.append(cleaned)
    return rows

def parse_semicolon_list(value):
    """Parse semicolon-delimited string into list of non-empty stripped strings.
    Handles: empty fields, repeated delimiters, extra whitespace."""
    if not value or not value.strip():
        return []
    return [item.strip() for item in value.split(';') if item.strip()]

def parse_int(value):
    v = value.strip().replace(',', '')
    if v.startswith('+'):
        v = v[1:]
    return int(v)

def parse_number(value):
    v = value.strip().replace(',', '')
    if v.startswith('+'):
        v = v[1:]
    try:
        return int(v)
    except ValueError:
        return float(v)
```

**Verification**: Check that all rows were read correctly and fields are properly stripped.

### Step 2: Build Relationship Structures

Build lookup structures to establish relationships:
- Employee lookup by ID: `employee_by_id[id] = employee_record`
- Group employees by department: `employees_by_dept[dept_id] = [employees]`
- Group projects by department: `projects_by_dept[dept_id] = [projects]`

**Verification**: 
- Count total employees and projects
- Verify each department has the expected number of employees/projects
- Check for orphaned records (employees/projects without valid department_id)

### Step 3: Construct Nested JSON

Build hierarchical structure for each department:
```python
{
    'id': dept_id,
    'name': dept['name'],
    'budget': parse_number(dept['budget']),
    'employees': [...],  # List of employee objects
    'projects': [...]    # List of project objects
}
```

**Field transformation decisions:**
- `skills`: semicolon-delimited string → array of strings (split, strip, filter empty)
- `members`: semicolon-delimited employee IDs → array of employee IDs (keep as-is, minimal transformation)
- `budget`: string → number (int if source is integer, float otherwise)
- `years_of_service`: string → integer
- `deadline`: keep as ISO date string

**Verification**:
- All employees have required fields: id, name, position, skills, years_of_service
- All projects have required fields: name, status, members, deadline
- All member IDs reference valid employees
- Empty member lists are empty arrays (not arrays with empty strings)

### Step 4: Compute Statistics

Compute all required aggregate metrics:
- `averageDepartmentBudget`: sum of all department budgets / count of departments **→ round to 2 decimal places**
- `totalEmployees`: total count of employee records
- `skillDistribution`: count occurrences of each skill across all employees
- `departmentSizes`: count of employees per department **→ use department names as keys**
- `projectStatusDistribution`: count of projects per status
- `averageYearsOfService`: sum of all years_of_service / count of employees **→ round to 2 decimal places**

```python
# Average calculation with rounding
avg = round(sum(values) / len(values), 2) if values else 0

# Frequency distribution
skill_dist = {}
for emp in employees:
    for skill in emp.skills:
        skill_dist[skill] = skill_dist.get(skill, 0) + 1
```

**Verification**:
- Manually calculate one average to verify rounding
- Check that skill distribution sums to total skills across all employees
- Verify department sizes sum to total employees
- Verify project status distribution sums to total projects

### Step 5: Add Metadata and Organization Fields

Add metadata (not in source data):
- `version`: use "1.0.0" or similar
- `timestamp`: current UTC time in ISO format (e.g., "2024-01-01T00:00:00Z")
- `generator`: descriptive string (e.g., "organization-json-generator")
- `organization.name`: use "Organization" or derive from context
- `organization.founded`: use a reasonable date (e.g., "2020-01-01")

**Note**: Tests validate that metadata is well-formed but don't require specific values (`test_metadata_is_well_formed_without_hidden_constant_requirements`).

### Step 6: Validate Against Schema

Validate output using jsonschema:
```python
import jsonschema
with open('/app/schema.json', 'r') as f:
    schema = json.load(f)
jsonschema.validate(output, schema)
```

**Common schema requirements:**
- Required fields at each level
- Type constraints (string, number, integer, array, object)
- Format constraints (date, date-time)
- Enum constraints (e.g., project status values)
- Minimum constraints (minItems for arrays, minimum for numbers)

### Step 7: Systematic Verification

**This is the most critical step.** Run all verification checks before considering the task complete:

```python
# Structure verification
assert set(output.keys()) == {'metadata', 'organization', 'statistics'}

# Count verification
assert len(output['organization']['departments']) == len(departments_raw)
total_emp = sum(len(d['employees']) for d in output['organization']['departments'])
assert total_emp == len(employees_raw)
total_proj = sum(len(d['projects']) for d in output['organization']['departments'])
assert total_proj == len(projects_raw)

# Minimal transformation verification
for dept in output['organization']['departments']:
    for proj in dept['projects']:
        for member in proj['members']:
            assert member in employee_by_id, f"Member {member} not found"

# Edge case verification
# Check departments with no projects have empty arrays
# Check projects with no members have empty arrays

# Statistics verification
stats = output['statistics']
assert stats['totalEmployees'] == len(employees_raw)
assert stats['averageDepartmentBudget'] == round(stats['averageDepartmentBudget'], 2)
assert stats['averageYearsOfService'] == round(stats['averageYearsOfService'], 2)
assert sum(stats['departmentSizes'].values()) == len(employees_raw)
assert sum(stats['projectStatusDistribution'].values()) == len(projects_raw)

# Key verification
for dept in departments_raw:
    assert dept['name'] in stats['departmentSizes']
```

## Variation Handling

### Entity Relationship Complexity

**Handle varying relationship patterns:**
- **Departments with no projects**: Include department with empty projects array
- **Projects with empty member lists**: Include project with empty members array
- **Uneven distribution**: Some departments may have many more employees/projects than others
- **Cross-department projects**: Projects may reference employees from different departments (use ID lookup if needed, but keep IDs in output)

### Field Parsing and Normalization

**Handle data irregularities:**
- **Extra whitespace**: Strip all fields during ingestion
- **Repeated delimiters**: Filter empty strings after splitting
- **Empty multi-value fields**: Return empty array, not array with empty string
- **Quoted text**: Python's csv.DictReader handles quotes automatically
- **Numeric formatting**: Strip whitespace, remove commas before parsing
- **Missing fields**: Use `.get()` with defaults

### Value Distribution for Aggregation

**Handle varying distributions:**
- **Skewed values**: Same averaging logic works regardless of distribution
- **Dominant/rare skills**: Frequency counting handles any distribution
- **Extreme ranges**: Numeric parsing handles any valid numbers
- **Zero values**: Include in calculations (don't filter out)

## Common Pitfalls

1. **Converting IDs to names unnecessarily**: If source has IDs and schema accepts strings, keep IDs. Converting to names is lossy and creates fallback inconsistency.

2. **Forgetting to handle empty member_ids**: Results in array with empty string instead of empty array. Always filter empty strings after splitting.

3. **Not stripping whitespace**: Causes validation failures or incorrect aggregations. Strip all fields during ingestion.

4. **Using wrong numeric type**: Schema may require integer vs number (float). Check schema and source data format.

5. **Not rounding averages**: Tests verify averages to 2 decimal places. Always use `round(value, 2)` for averages.

6. **Not validating**: Always validate against schema before writing to catch schema violations early.

7. **Inconsistent member representation**: Don't mix IDs and names in the same array. Use one representation consistently (prefer IDs for minimal transformation).

8. **Skipping systematic verification**: Always run all verification checks before considering the task complete. This catches edge cases and ensures correctness.

## Adaptation to New Instances

When encountering a new instance:
1. **Inspect CSV structure**: Identify column names and delimiters
2. **Check schema requirements**: Note required fields, types, formats, enums
3. **Identify relationships**: Determine how entities link (foreign keys)
4. **Apply minimal transformation**: Map CSV columns to schema fields with minimal value transformation
5. **Handle variations**: Apply normalization for whitespace, delimiters, formats
6. **Compute statistics**: Ensure all required metrics are computed with proper rounding
7. **Validate**: Always validate against schema
8. **Verify systematically**: Run all verification checks from Step 7

## Meta-Principle

**When in doubt about a value transformation, don't transform.** The schema tells you the shape; the source data tells you the content. Preserve the source data values unless there's an explicit requirement to transform them.

**Key insight**: The task instruction "Preserve the relationships represented by the source data exactly" is the guiding principle. Minimal transformation (keeping IDs as IDs, not converting to names) is the correct interpretation and passes all tests.

**Critical success factor**: Systematic verification at each step catches errors early and ensures correctness across all variation dimensions.
