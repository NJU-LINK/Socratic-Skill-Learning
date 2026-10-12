# Iteration 3 Summary: Complex Access Policy Topologies

## Analysis of Iteration 2

**Result**: 5/5 tests passed ✅

The solver successfully executed the v01 task by following the worked example almost verbatim. The skill performed well for the basic scenario with:
- Two collaborators (alice, bob) with full access
- One restricted user (runner) with read/traverse access
- Simple inheritance requirements

## Identified Weakness

The most consequential weakness for unseen variants is the **lack of a systematic decision framework** for handling complex access policy topologies. The spec's variation axes explicitly mention:

1. **access_policy_topology**: "different mixes of named users and groups, principals whose access comes partly from group membership and partly from explicit ACL entries, additional denied principals beyond the generic others class"

2. **permission_model**: "policies that rely on the ACL mask to preserve or restrict named entry permissions, and tasks where the effective access pattern is more subtle than simply granting everyone full control"

3. **inheritance_and_group_propagation**: "setups where group propagation and inherited ACLs must continue to work under different creator identities and creation orders"

The existing skill covered individual users and single groups but lacked guidance for:
- Multiple groups with different permission levels
- Users who are members of multiple groups
- Asymmetric access patterns (Team A can read Team B's files but not vice versa)
- Complex denial scenarios where users must be denied despite group membership

## Improvements in Iteration 3

### Added: Complex Access Policy Topologies Section (lines 396-546)

#### 1. Decision Framework: From Requirements to ACL Entries

A systematic 4-step methodology for translating complex requirements into ACL configuration:

**Step 1**: Create a principal table identifying all users/groups and their required access levels

**Step 2**: Determine the mask based on the most permissive named entry

**Step 3**: Handle overlapping memberships using named user entries to override group entries

**Step 4**: Set both access and default ACLs for each principal

Includes a complete worked example with:
- Multiple users (alice, bob)
- Multiple groups (developers, reviewers, auditors)
- Overlapping memberships (auditor in developers but needs only r--)
- Explicit denial (intern in developers but denied)

#### 2. Multiple Groups with Different Permission Levels

Demonstrates how to configure ACLs when multiple groups need different access:
- developers: rwx
- reviewers: r-x
- auditors: r--

Shows mask calculation (must be rwx to accommodate developers) and explains effective permissions for each group.

Addresses the question: "What happens when a user is in multiple groups?" Answer: The kernel uses the most permissive matching group entry.

#### 3. Asymmetric Access Patterns

Provides a pattern for collaboration scenarios where access is not symmetric:
- Team A (alice, bob) can read and write Team B's files
- Team B (charlie, dave) can only read Team A's files

Shows how to use named user entries for fine-grained control when group-based asymmetric access is needed.

#### 4. Denial Patterns Beyond `other::---`

Two patterns for complex denial scenarios:

**Pattern 1**: Deny a user who is in a granted group
```bash
setfacl -m g:developers:rwx /path
setfacl -m u:intern:--- /path  # Overrides group entry
```

**Pattern 2**: Deny a specific group
```bash
setfacl -m g:developers:rwx /path
setfacl -m g:contractors:--- /path
```

Explains that if a user matches multiple group entries, the most permissive is used, so named user entries are required for reliable denial.

## Verification

All new patterns were tested in the container environment:

✅ Multiple groups with different permission levels (developers:rwx, reviewers:r-x, auditors:r--)
✅ User in multiple groups (alice in both developers and reviewers)
✅ Denial pattern (nobody denied despite developers group membership)
✅ Asymmetric access (testuser1:rwx, testuser2:r-x)

## Impact on Generalization

This improvement significantly enhances the skill's ability to handle unseen variants by:

1. **Providing a decision framework** rather than just examples, enabling the solver to analyze novel requirements systematically

2. **Addressing the full spec variation space** for access_policy_topology, including complex mixes of users and groups, overlapping memberships, and denial patterns

3. **Explaining mask calculation** when multiple permission levels exist, which is critical for "policies that rely on the ACL mask to preserve or restrict named entry permissions"

4. **Covering asymmetric access patterns** for collaboration scenarios where different teams have different access rights

5. **Clarifying group membership precedence** rules, which is essential when "principals whose access comes partly from group membership and partly from explicit ACL entries"

## Skill Statistics

- **Total lines**: 701 (up from 540 in iteration 2)
- **New sections**: 4 subsections under "Complex Access Policy Topologies"
- **New examples**: 3 complete worked examples for complex scenarios
- **Maintained**: All existing content from iterations 1-2

## Conclusion

Iteration 3 transforms the skill from a collection of patterns for simple scenarios into a comprehensive methodology for handling complex access policy topologies. The decision framework enables systematic analysis of novel requirements, while the specific patterns for multiple groups, asymmetric access, and complex denial provide concrete solutions for the variation dimensions described in the spec.

The skill now addresses the full range of access_policy_topology variations while maintaining the strong foundation from iterations 1-2 for basic scenarios and inheritance mechanics.
