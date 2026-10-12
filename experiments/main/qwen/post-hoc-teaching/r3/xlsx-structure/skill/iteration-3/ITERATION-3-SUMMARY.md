# Iteration 3 Summary: Composition Guidance

## Overview
Iteration 3 focused on addressing the most consequential weakness for generalization: **the lack of explicit guidance on composing multiple transformations**. While the skill had 18 individual patterns, real-world tasks often require chaining operations, and the skill didn't provide guidance on how to do this correctly.

## Key Changes

### 1. Added "Composing Transformations" Section
A comprehensive new section covering:

#### Order of Operations
Established a clear order for chaining transformations:
1. **Selection/Filtering first** - Identify which rows/cells to operate on
2. **Structural transformations second** - Rearrange the selected data
3. **Data alignment third** - Match and reconcile data across ranges
4. **Output operations last** - Write to final destination

**Rationale:**
- Filtering first reduces scope, making subsequent operations faster
- Structural changes before alignment ensures IDs/values are in correct positions
- Output operations last ensures the final result is written correctly

#### Common Composition Patterns
Provided three concrete examples:
1. **Filter → Sort → Extract**: Filter rows, detect blocks, sort within blocks, extract to destination
2. **Style Selection → ID Alignment → Reconcile**: Select by style, build ID map, reconcile with destination
3. **Membership Filter → Reorder → Transpose**: Filter by membership, reorder to match source list, transpose result

#### Data Flow Between Transformations
Key principles for correct composition:
- Preserve styles throughout (use `preserve_styles=True` in all operations)
- Track row ranges (each transformation may change the range)
- Capture before rearranging (use `capture_row()` before moving data)
- Write after all transformations (minimize intermediate writes to avoid style loss)

#### Anti-Patterns to Avoid
- ❌ Don't sort then filter (wastes effort sorting rows that will be discarded)
- ❌ Don't transpose then sort (transposing changes data structure)
- ❌ Don't write intermediate results (each write can lose styles)
- ❌ Don't ignore row range changes (update tracking between steps)

#### Multi-Step Workflow Example
Complete example showing how to:
1. Select rows by style
2. Capture all selected rows with styles
3. Evaluate formulas in captured data
4. Sort by column D
5. Write to destination in one operation

### 2. Added Composition Pitfalls (#20-22)

**Pitfall #20: Composition order matters**
- Applying transformations in wrong order can cause wasted effort, data loss, or incorrect results
- Always follow the order: filter → sort → align → output

**Pitfall #21: Track row range changes through composition**
- Each transformation may change the row range
- After filtering: `[dest_start_row, next_write - 1]`
- After transposing: rows become columns
- Always update range tracking between steps

**Pitfall #22: Minimize intermediate writes in compositions**
- Each write operation can lose styles if not done carefully
- Chain transformations in memory (capture → transform → transform → write)
- Don't write after each step

### 3. Extended Verification Checklist
Added 5 new verification items for composition:
- [ ] Multiple transformations are composed in correct order
- [ ] Row ranges are tracked correctly through composition pipeline
- [ ] Styles are preserved through all transformation steps
- [ ] Formulas are evaluated before sorting/filtering operations
- [ ] Data is captured once, transformed in memory, written once

## Coverage Matrix

| Category | Iteration 2 | Iteration 3 | Total |
|----------|-------------|-------------|-------|
| **Transformation Types** | 10 | 0 | 10 |
| **Selection Rules** | 9 | 0 | 9 |
| **Key Functions** | 18 | 0 | 18 |
| **Pitfalls** | 19 | +3 | 22 |
| **Verification Items** | 14 | +5 | 19 |
| **Composition Patterns** | 0 | +3 | 3 |

## Generalization Achievement

The skill now provides:
1. **Complete pattern library** for all spec-declared transformation types
2. **Consistent style preservation** across all data-moving functions
3. **Systematic classification** via enhanced decision framework
4. **Composition guidance** for chaining multiple transformations
5. **Comprehensive pitfalls** including composition-related failures
6. **Extended verification checklist** ensuring correctness across variants

## Key Insight

The most consequential weakness wasn't missing patterns or incorrect implementations—it was the **lack of guidance on how to combine patterns**. Real-world tasks rarely involve just one transformation; they require chaining multiple operations in the correct order. Without explicit guidance, agents might:
- Apply transformations in the wrong order
- Lose data or styles between steps
- Create inefficient or incorrect workflows

By adding composition guidance, the skill now addresses the full complexity of real-world xlsx transformation tasks, not just individual operations.

## Meta-Lesson

When building a skill with multiple patterns, don't just provide the patterns—provide guidance on **how to combine them**. The patterns are the building blocks, but composition is the architecture. Both are essential for generalization.
