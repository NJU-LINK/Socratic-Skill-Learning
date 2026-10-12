# Iteration 2 Improvements

## Critical Fix: cmd.sh Format

**Problem**: Test `test_jq_command_file_and_replay_work` failed because it asserts `command.strip().startswith("jq ")`, but the SKILL.md instructed writing cmd.sh with a `#!/bin/bash` shebang line.

**Root Cause**: The skill's cmd.sh example included:
```bash
#!/bin/bash
jq '<filter_expression>' /app/input.json > /app/output.json
```

This caused the solver to write cmd.sh starting with `#!/bin/bash`, which failed the test assertion.

**Fix**: Updated the cmd.sh section to explicitly state:
- The file must contain ONLY the raw jq command
- No shebang (`#!/bin/bash`), no comments, no blank lines before the command
- The first non-whitespace characters must be `jq `
- Added a "Critical" warning about the test assertion

**Updated Example**:
```bash
jq '<filter_expression>' /app/input.json > /app/output.json
```

**Verification Checklist**: Added explicit check: "cmd.sh starts with `jq ` (no shebang, no comments)"

## Previous Fixes Retained

All fixes from iteration 1 remain in place:
1. No bare `| trim` function calls (jq has no trim built-in)
2. No `trim_lower` references (replaced with explicit `gsub | ascii_downcase`)
3. Correct `--indent` guidance (jq 1.6 doesn't support it)
4. jq version differences documented (1.6 vs 1.7+)
5. All whitespace trimming uses `gsub("^\\s+|\\s+$";"")`

## Impact

This fix addresses the single test failure (13/14 → 14/14 expected). The failure was caused by following incorrect artifact format guidance in the skill, not by incorrect jq logic.
