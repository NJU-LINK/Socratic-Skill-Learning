---
name: filter-js-from-html
description: Reusable instructions for filter-js-from-html tasks.
---

# filter-js-from-html

[RULE 001] Solve and verify
content: Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.

[RULE 002] Decode entities before protocol check
content: When checking URL-bearing attribute values for dangerous protocol schemes, fully decode all HTML entities and strip all whitespace and control characters before matching, so that obfuscated protocol names embedded with entity references or invisible characters are still detected.

[RULE 003] Remove rather than neutralize dangers
content: When sanitizing markup to eliminate executable behavior, delete dangerous URL-bearing attributes entirely rather than overwriting their values with placeholders, remove inline style attributes and style elements containing executable CSS constructs such as javascript: URLs inside url() or CSS expression calls, remove container elements that embed content from other namespaces, and remove animation elements whose target attribute would inject a dangerous value into a link or reference attribute.
