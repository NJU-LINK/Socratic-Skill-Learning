---
name: cross-entropy-method
description: General starting point for solving tasks in the cross-entropy-method family.
---

# cross-entropy-method

Read the public task carefully, inspect the available inputs, implement a solution, and verify the result before finishing.



## Implementation Guidance
- **Reset state before each trajectory**: When evaluating a batch of independent plans from a fixed start state, explicitly reset the environment's state (e.g., position to origin) at the beginning of *every* plan's simulation loop. Failing to reset causes trajectories to chain together, producing incorrect rewards and silently corrupting persistent prefix memoization caches. Always save and restore the environment's internal state before and after batch plan evaluation to prevent side effects.
- **Proven Patterns**: See [CEM Implementation Patterns](references/implementation-patterns.md) for detailed code snippets and strategies covering prefix-based memoization, independent per-axis state clipping, and deterministic column-wise RNG sampling.
