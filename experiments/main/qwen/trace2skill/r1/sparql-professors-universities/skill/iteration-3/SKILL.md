---
name: sparql-professors-universities
description: General starting point for solving tasks in the sparql-professors-universities family.
---

# sparql-professors-universities

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Workflow

1. **Inspect Data First**: Read the `.ttl` file (e.g., via `cat` or `head`) before writing queries to map exact predicate chains, graph traversal paths, and literal value formats. Do not guess predicate names.
2. **Filter Role Variants**: Use substring matching like `FILTER(CONTAINS(?role, "Professor"))` to capture variations (e.g., 'Assistant Professor') without exhaustive exact-match lists.
3. **Multi-hop Traversal**: Link entities through intermediate nodes when needed, such as connecting a person to a top-level university via their department:
   ```sparql
   ?person uni:worksAt ?department .
   ?department uni:partOfUniversity ?university .
   ```
4. **Verify Locally**: Validate your `.sparql` query against the local `.ttl` file using `rdflib` to confirm syntax, path correctness, and expected row counts before finalizing:
   ```bash
   python3 -c "from rdflib import Graph; g = Graph(); g.parse('data.ttl', format='turtle'); results = g.query(open('query.sparql').read()); print(len(results))"
   ```