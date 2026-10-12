# Learning Summary: Organization JSON Generator

## Initial Approach and Mistakes

### First Attempt: Name-Based Member Resolution

My initial implementation converted project `member_ids` (e.g., "D001-E001;D001-E002") to employee names by looking up each ID in the employee data. This seemed intuitive because:
- The output field is called "members" (suggests names)
- Names are more human-readable
- It felt like "resolving" the relationships

**Problems with this approach:**

1. **Fallback inconsistency**: When an ID didn't match an employee, I fell back to keeping the ID, creating a mixed array of names and IDs
2. **Lossy transformation**: Names aren't unique; multiple employees could have the same name
3. **Added complexity**: Required reliable lookups for every instance
4. **Violated "preserve exactly"**: The instruction said to preserve relationships exactly, but I was transforming IDs to names

### Teacher Feedback: The Minimal Transformation Principle

The Teacher identified this as the highest-risk design decision and explained:

> "When a task says 'Preserve the relationships represented by the source data exactly', the safest default is minimal transformation of the data values themselves."

**Key insight**: The schema tells you the **shape** (types, required fields), but the source data tells you the **content** (actual values). If the source provides IDs and the schema accepts strings, keeping IDs is:
- A valid, lossless transformation
- The same code path for all instances
- Robust against edge cases

## Corrected Approach

### Minimal Transformation Applied

Changed from:
```python
# Convert member IDs to employee names
member_names = []
for mid in member_id_list:
    if mid in employee_by_id:
        member_names.append(employee_by_id[mid]['name'])
    else:
        member_names.append(mid)  # Fallback creates inconsistency
```

To:
```python
# Keep member IDs as-is (minimal transformation)
member_ids = parse_semicolon_list(proj.get('member_ids', ''))
```

This is simpler, more robust, and truly preserves the relationship data.

## Key Learnings

### 1. The "Preserve Exactly" Principle

When the task says "preserve relationships exactly":
- **Don't transform values** unless explicitly required
- **Keep source data format** if schema accepts it
- **Minimal transformation** = split/strip/filter, not semantic conversion

### 2. Schema vs Source Data

- **Schema** = shape (types, required fields, formats, constraints)
- **Source data** = content (actual values to put in those fields)
- Don't conflate field names with semantic requirements

### 3. Robustness Through Simplicity

The ID-based approach handles all variations:
- Empty member lists → empty array
- Missing employees → no lookup needed
- Cross-department projects → same code path
- Dense reuse patterns → no complexity added

### 4. Edge Case Handling

**Empty multi-value fields:**
- Wrong: `[""]` (array with empty string)
- Right: `[]` (empty array)
- Solution: Filter empty strings after splitting

**Departments with no projects:**
- Include department with empty projects array
- Don't skip the department

**Projects with no members:**
- Include project with empty members array
- Don't skip the project

### 5. Numeric Parsing

Handle formatting variations:
- Strip whitespace
- Remove thousands separators (commas)
- Handle leading + signs
- Try int first, fall back to float

### 6. Statistics Computation

- **Averages**: `sum(values) / len(values) if values else 0`
- **Distributions**: Frequency counting with `.get(key, 0) + 1`
- **Include all values**: Don't filter out zeros or extremes

## Secondary Considerations

### Department Sizes Keys

Used department names as keys (e.g., "Engineering": 3). This is reasonable for reporting, but:
- Names could theoretically change
- IDs would be more stable
- If tests expect IDs, adjust accordingly

### Organization Metadata

Fields like `organization.name` and `organization.founded` aren't in the source CSVs. Used reasonable defaults:
- `name`: "Organization"
- `founded`: "2020-01-01"

These are assumptions. If tests fail, look for additional data sources or conventions.

## Verification Checklist

1. ✓ Schema validation passes
2. ✓ All departments present (including those with no projects)
3. ✓ All employees present with correct data
4. ✓ All projects present with correct data
5. ✓ Members are IDs (minimal transformation)
6. ✓ Empty member lists are empty arrays (not `[""]`)
7. ✓ Statistics computed correctly
8. ✓ Numeric types match schema (int vs float)
9. ✓ Dates are ISO format strings
10. ✓ All required fields present at every level

## Meta-Principle

**When in doubt about a value transformation, don't transform.** The schema tells you the shape; the source data tells you the content. Preserve the source data values unless there's an explicit requirement to transform them.

This principle applies broadly:
- CSV → JSON transformations
- Data migration tasks
- API response formatting
- Any task that says "preserve" or "maintain" data

## Skill Evolution

The SKILL.md evolved from:
1. **Initial**: Focused on implementation details, included name-conversion logic
2. **After feedback**: Emphasized minimal transformation principle, removed name-conversion
3. **Final**: Clear meta-principle, robust edge case handling, variation-aware design

The skill is now:
- **General**: Handles all variations in the family
- **Robust**: Handles edge cases without special logic
- **Principled**: Based on clear reasoning about data preservation
- **Testable**: Easy to verify against schema and requirements
