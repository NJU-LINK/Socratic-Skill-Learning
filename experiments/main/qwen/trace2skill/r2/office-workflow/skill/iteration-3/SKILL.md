---
name: office-workflow
description: General starting point for solving tasks in the office-workflow family.
---

# office-workflow

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.


## Proven Patterns

- **Email Parsing (.eml)**: Use `email.message_from_binary_file(f, policy=policy.default)` and iterate `msg.walk()` checking `part.get_content_type() == 'text/plain'` to reliably extract body text. See [Email Parsing and Text Output Formatting](references/email-and-text-outputs.md) for detailed code snippets.
- **Strict Text Formatting**: To separate blocks with one blank line and end with exactly one newline, use `"\n\n".join(blocks) + "\n"`. Verify the output programmatically: `data.endswith(b'\n') and not data.endswith(b'\n\n')`.
- **File Ordering**: Filesystem globbing is not guaranteed to be alphabetical. Explicitly sort `Path.glob()` results (e.g., `sorted(..., key=lambda p: p.name)`) for deterministic output.