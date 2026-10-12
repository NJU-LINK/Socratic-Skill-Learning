---
name: organization-json-generator
description: General starting point for solving tasks in the organization-json-generator family.
---

# organization-json-generator

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Data Mapping Rules
- **Preserve Foreign Key IDs**: When mapping CSV columns containing foreign key identifiers (e.g., `member_ids`) to JSON array fields, map the original ID values directly as strings. Do not resolve them to human-readable names unless the schema or instructions explicitly require it, as downstream validations often check referential integrity using the original IDs.
- **Verify Relational Integrity**: Ensure that referenced IDs (e.g., project members) are a valid subset of the parent entity's IDs (e.g., department employees) before finalizing the output.

## Proven Workflow
1. **Parse Delimited Fields Safely**: When processing CSV columns with delimited lists (e.g., semicolon-separated), use `[x.strip() for x in field.split(';') if x.strip()]` to handle empty fields and whitespace without injecting empty strings.
2. **Assemble and Validate Against Schema**: Group child records (e.g., employees, projects) under parent departments using foreign keys. Immediately validate the generated JSON against the provided schema using `jsonschema` to catch structural or type mismatches.
3. **Aggregate with Type Awareness**: Compute statistics (averages, totals) directly from parsed data. Strictly respect schema types: use floats for averages and integers for counts.
