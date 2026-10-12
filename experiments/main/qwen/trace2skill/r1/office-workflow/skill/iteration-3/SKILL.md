---
name: office-workflow
description: General starting point for solving tasks in the office-workflow family.
---

# office-workflow

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Strategies

- **Parsing `.eml` files**: Use Python's built-in `email` module (`email.message_from_binary_file`, `msg.walk()`, `email.header.decode_header`) instead of regex or string splitting to correctly handle MIME boundaries and decode headers/payloads.
- **Strict formatting verification**: When tasks require exact whitespace or newline constraints, read the output file in binary mode (`'rb'`) and print `repr(content)` to verify invisible whitespace and exact trailing newlines.
- **Deterministic output**: When aggregating multiple files, sort the processed artifacts by source filename (e.g., `os.path.basename`) before writing the final output.

## References

- [references/python-utilities.md](references/python-utilities.md): Proven Python patterns for parsing `.eml` files, formatting multi-block text output, and ensuring deterministic file ordering.
