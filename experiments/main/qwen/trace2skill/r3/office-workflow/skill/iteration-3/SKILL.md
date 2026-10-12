---
name: office-workflow
description: General starting point for solving tasks in the office-workflow family.
---

# office-workflow

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Workflows & Verification

- **Strict Text Formatting**: Verify exact text formatting (e.g., trailing newlines, blank line separators) using byte-level inspection (`open('file', 'rb').read()`) or `cat -A output.txt` to visualize line endings. Do not rely on standard terminal output.
- **Test Harness Contract**: Before finishing, verify the solution script exposes the required callable function (e.g., `run()`) and executes without errors. Run `python -c "from solve import run; run()"` to ensure correct imports and side effects.

## References

- [Python Patterns](references/python-patterns.md): Proven Python snippets for common office tasks like parsing `.eml` files and formatting multi-block text outputs.