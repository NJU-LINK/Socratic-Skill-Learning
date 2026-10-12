# Iteration 3: Removing v01-Specific Remnants

## Overview

Iteration 2 achieved a perfect score (6/6 tests passed). The skill correctly captured the verification contract principle and noise calibration formula. However, one v01-specific remnant remained in the implementation pattern comments that could mislead solvers on variants.

## Issue Identified

### Hardcoded Noise Range in Comments

**Location**: SKILL.md, Stage 1 implementation pattern, lines 52-54

**Before**:
```python
# 3. Add noise - IMPORTANT: use sufficient amplitude
# Typical range: sigma=0.05 to 0.15 (before RMS normalization)
# After normalization, this becomes ~0.005 to 0.015
signal += noise_function(num_samples)
```

**Problem**: These comments hardcode v01-specific noise ranges, directly contradicting the calibration formula principle documented in the same file's "Critical Details" section. A solver working on a variant with different noise requirements might:
1. Follow the hardcoded comments instead of applying the formula
2. Use sigma=0.1 without calibrating for the variant's specific requirements
3. Fail tests that check residual_std bounds

**Why this matters**: The Teacher's lesson 2-2 emphasized capturing principles over implementations. The calibration formula is the principle; the specific sigma values are v01 implementations. Mixing them creates confusion.

## Fix Applied

### Removed Hardcoded Range

**After**:
```python
# 3. Add noise
# Calibrate noise_sigma using the formula in Critical Details section
signal += noise_function(num_samples)
```

This change:
- Removes the v01-specific hardcoded values
- Points the solver to the calibration formula (the principle)
- Ensures consistency across the document

## Additional Improvement: CSV Precision Guidance

### Added Precision Requirements

**Location**: SKILL.md, Stage 2 CSV Export section

**Addition**:
```
- **Numerical precision**: Use sufficient precision to pass test tolerance checks. 
  Format like `:.10e` or `:.10g` provides ~10 significant digits, which is safe for 
  typical tolerances (rel_tol=1e-6). For tighter tolerances, use `:.15g` or higher.
```

**Rationale**: While not critical for v01 (the solver used `:.10e` which worked fine), variants might have tighter tolerances. Explicit guidance prevents subtle failures due to insufficient precision.

**Verification**: Tested various format strings:
- `.6e` → max_rel_err=2.25e-07 (PASS for rel_tol=1e-6)
- `.8e` → max_rel_err=1.67e-09 (PASS)
- `.10e` → max_rel_err=3.16e-11 (PASS)
- `.15g` → max_rel_err=2.86e-15 (PASS for very tight tolerances)

## Verification Results

After applying the fixes, the implementation still passes all v01 requirements:

✅ **WAV file**: 12kHz, 2.5s, mono, RMS=0.149989 (within 0.15±0.002)
✅ **Residual std**: 0.010564 (in range [0.004, 0.02])
✅ **Magnitude CSV**: Matches STFT computed from WAV signal (all sample indices pass math.isclose with rel_tol=1e-6, abs_tol=1e-9)
✅ **Peaks CSV**: 153 frames, correct top-3 bins [46, 31, 15] for frame 0
✅ **PEAKS_ONLY mode**: Functional
✅ **Dynamic header**: Works for any top_k value

## Key Learnings

### 1. Consistency Within Documentation

When a document captures both principles and examples, ensure they don't contradict each other. The calibration formula (principle) and the hardcoded range (example) were in the same file, creating confusion.

**Lesson**: After documenting a principle, scan the entire document for any remnants that contradict it.

### 2. Comments Can Be Misleading

Code comments are often followed more closely than prose documentation. A comment saying "Typical range: sigma=0.05 to 0.15" will be followed even if the prose says "use the calibration formula."

**Lesson**: Comments should reference principles, not hardcode implementations. Use comments to point to the relevant section of the documentation.

### 3. Precision Guidance Prevents Subtle Failures

Even when the default precision works, explicitly documenting precision requirements helps solvers:
1. Understand why a particular format was chosen
2. Adapt to variants with different tolerances
3. Avoid trial-and-error when tests fail due to precision

**Lesson**: Document numerical precision requirements alongside schema requirements.

## Skill Package State

### Files Modified
- `skill/audio-synth-stft-peaks/SKILL.md`: Removed hardcoded noise range, added CSV precision guidance

### Files Unchanged
- All other skill documentation files (DEVELOPMENT.md, README.md, etc.)
- Implementation files in /app/ (still work correctly)

### Skill Quality
- ✅ Captures principles (verification contract, calibration formula)
- ✅ Labels v01-specific details as such
- ✅ Provides adaptation guidance for variants
- ✅ Consistent throughout (no contradictions)
- ✅ Includes practical guidance (precision, efficiency)

## Conclusion

Iteration 3 was a minor but important refinement. The skill was already correct and working; this iteration removed a subtle inconsistency that could cause failures on variants. The changes ensure the skill is:
- **Principled**: Captures underlying concepts, not just implementations
- **Consistent**: No contradictions between prose and comments
- **Complete**: Includes practical guidance for edge cases
- **Generalizable**: Works across the full variation space defined in spec.yaml

The skill is now ready to handle variants correctly by guiding solvers to apply principles rather than follow hardcoded values.
