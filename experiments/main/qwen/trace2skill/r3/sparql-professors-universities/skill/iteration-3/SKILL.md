---
name: sparql-professors-universities
description: General starting point for solving tasks in the sparql-professors-universities family.
---

# sparql-professors-universities

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Query Patterns

- **Inspect the Graph Structure**: Always inspect the `.ttl` file to discover the exact chain of predicates linking entities rather than guessing from the task description.
- **Inclusive Role Filtering**: Use `FILTER(CONTAINS(?role, "Professor"))` on role strings to capture all valid professor variants (e.g., Assistant, Full) while excluding non-target roles like 'Lecturer' or 'Student'.
- **University Affiliation**: Traverse through the intermediate department node using a two-hop path. Do not assume a direct person-to-university link.
  ```sparql
  ?person uni:worksAt ?department .
  ?department uni:partOfUniversity ?university .
  ?university uni:hasName ?universityName .
  ```

## Validation Workflow

- **Local SPARQL Verification**: Use Python's `rdflib` to load the local `.ttl` file and execute the drafted SPARQL query. Print the results and row count to verify selected variables, confirm target entities are returned, and ensure distractors are filtered out before saving the final `.sparql` file. Ensure `python3-rdflib` is installed if needed.