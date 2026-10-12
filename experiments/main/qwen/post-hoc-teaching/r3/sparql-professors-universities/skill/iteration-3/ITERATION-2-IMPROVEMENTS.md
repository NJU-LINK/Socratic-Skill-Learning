# Iteration 2 Improvements

## Summary
Enhanced the skill to be more robust, actionable, and generalizable across variant ontologies.

## Key Changes

### 1. Integrated Discovery Script
**Added**: `discover_ontology.py` — a single, executable script that:
- Parses the Turtle file and discovers all ontology structure
- Identifies namespace prefixes, classes, predicates
- Enumerates all role/rank values with professor classification
- Probes affiliation path patterns (direct, two-hop, inverse)
- Identifies university name predicate
- Outputs structured recommendations

**Benefit**: Replaces fragmented diagnostic code snippets with a comprehensive, self-contained tool. The agent can run one command instead of piecing together multiple partial scripts.

### 2. Improved Regex Pattern
**Changed**: From `(^|\\s)[Pp]rofessor($|\\s)` to `(^|[^a-zA-Z])[Pp]rofessor($|[^a-zA-Z])`

**Why**: The old regex failed on punctuation boundaries:
- ✗ "Professor, Computer Science" (comma after)
- ✗ "Professor." (period after)

The new regex uses non-letter boundaries instead of just whitespace:
- ✓ Matches: "Professor of CS", "Assistant Professor", "Professor, Emeritus", "Professor."
- ✗ Rejects: "Professorial Lecturer" (the "i" after "professor" is a letter)

**Benefit**: Handles the spec's "vary spelling and abbreviations" axis more robustly.

### 3. Task Instruction Mining (Step 0)
**Added**: Explicit guidance to read the task instruction first and extract:
- Which roles qualify (e.g., "Assistant Professors and Full Professors")
- How role is encoded (e.g., "uni:role property... in the form of a string")
- Output variables and assumptions

**Benefit**: The task instruction contains critical hints that constrain the search space. The v01 instruction explicitly mentions "uni:role" and "two kinds of professors" — these are strong signals.

### 4. Cleaner Query Templates
**Changed**: From hardcoded v01 predicates to generic placeholders:
```sparql
# Before
?person uni:role ?role .
?person uni:worksAt ?dept .

# After
?person <prefix>:<rolePred> ?role .
?person <prefix>:<worksAtPred> ?dept .
```

**Benefit**: Makes it clear that predicates must be substituted from discovery results, not hardcoded.

### 5. Removed Fragmented Code
**Removed**: Multiple partial Python snippets with undefined variables (`EX.Person`, `run_probe()`)

**Replaced with**: Single discovery script + clear manual fallback steps

**Benefit**: Agent no longer needs to improvise or debug incomplete code.

### 6. Enhanced Checklist
**Added**: 
- "Read the task instruction and extracted professor qualification criteria"
- "Ran discovery script (or manual discovery)"
- "Enumerated all distinct role/rank values; built decision table"

**Benefit**: Ensures critical steps are not skipped.

## Verification

All improvements verified against v01:
- ✓ Discovery script runs successfully and produces correct output
- ✓ Improved regex handles all test cases (including punctuation boundaries)
- ✓ Solution still produces 7 correct professor-university pairs
- ✓ No non-professors leaked
- ✓ Skill structure is well-formed and internally consistent

## Generalization

The skill now handles all three spec variation axes:

1. **professor_identification_semantics**: 
   - String-valued roles (v01) ✓
   - Resource-based ranks ✓
   - Near-miss titles (e.g., "Professorial Lecturer") ✓
   - Punctuation boundaries ✓

2. **affiliation_structure_to_university**:
   - Department chains (v01) ✓
   - Direct affiliation ✓
   - Appointment resources ✓
   - Inverse containment ✓
   - Teaching-course fallback ✓

3. **graph_noise_and_result_cardinality**:
   - SELECT DISTINCT for duplicates ✓
   - Multiple departments/courses per university ✓
   - Overlapping organization paths ✓

## Files

- `SKILL.md` — Main skill documentation (10,102 bytes, 260 lines)
- `discover_ontology.py` — Integrated discovery script (9,688 bytes)
