---
name: organization-json-generator
description: General starting point for solving tasks in the organization-json-generator family.
---

# organization-json-generator

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Recommended Implementation Patterns

### Relational CSV to Nested JSON
Build a dictionary of parent entities keyed by their primary ID. Iterate through child records, extract the foreign key, and append the transformed child object to the parent's corresponding list to ensure correct nesting without complex joins.

### Delimited String Parsing
When converting delimited strings (e.g., semicolon-separated values) into JSON arrays, use a list comprehension that splits by the delimiter, strips whitespace, and filters out empty strings: `[s.strip() for s in row['field'].split(';') if s.strip()]`. This prevents phantom entries like `['']`.

### Pre-Submission Schema Validation
After generating the output JSON, use a validation library (like Python's `jsonschema.validate(data, schema)`) to programmatically verify that the output conforms to the provided schema file. This catches type mismatches, missing required fields, or enum violations before finishing.