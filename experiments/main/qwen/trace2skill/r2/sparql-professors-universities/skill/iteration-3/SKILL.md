---
name: sparql-professors-universities
description: General starting point for solving tasks in the sparql-professors-universities family.
---

# sparql-professors-universities

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Workflow

1. **Inspect the Schema/TTL and Map Predicate Chains**: Before writing queries, inspect the TTL or schema file to map the exact multi-hop property chain. Do not guess predicates; verify intermediate nodes. For example, university affiliations often require a chain through the department:
   ```sparql
   ?person uni:worksAt ?department .
   ?department uni:partOfUniversity ?university .
   ?university uni:hasName ?universityName .
   ```
2. **Filter Role Variants with CONTAINS**: When filtering roles represented as string literals (e.g., 'Professor', 'Assistant Professor'), use `FILTER(CONTAINS(?role, 'Professor'))` to capture all variants safely and exclude other roles like 'Lecturer' or 'Student', avoiding complex regex or multiple `UNION` blocks.
3. **Validate Locally with rdflib**: Before finalizing, use Python's `rdflib` to load the local TTL file and execute the drafted SPARQL query. Verify result cardinality, expected variable bindings, and proper exclusion of non-target entities to catch syntax or logical errors early.