---
description: Validate implementation against design intent, codebase patterns, and code quality
model: opus
argument-hint: "thoughts/qrspi/<id>/"
---

# Validate — Three-Layer Quality Gate

Validate completed implementation against design intent, codebase patterns, and code quality before committing or creating a PR.
Catches problems when they're cheapest to fix.

## Input

Read these files from `$ARGUMENTS`:
- `task.md` — original intent
- `design.md` — desired end state and resolved decisions
- `research.md` — patterns and conventions discovered during research
- `plan.md` — verify all phases are checked off (`- [x]`)

If any plan checkboxes are unchecked, stop and tell the user to finish implementation first.

## Process

### Layer 1: Functional Validation

Compare what was built against what was intended.

1. Read the "Desired End State" section of `design.md`.
2. For each stated outcome, verify the code achieves it:
   - Read the relevant files
   - Run any verification commands from `plan.md`
   - Check the outcome is met
3. Read the "What We're NOT Doing" section — verify no scope creep occurred.
4. Read `task.md` — confirm the original problem is solved.

Present findings:
```
## Functional Validation

- [x] [outcome achieved]
- [x] [outcome achieved]
- [ ] [outcome NOT met — description of gap]

Scope creep check: [clean | items found]
```

Do not prescribe fixes for unmet outcomes. Report what's missing — the human decides how to address it.

### Layer 2: Pattern Compliance

Compare new code against codebase conventions using `research.md` as reference.

Spawn two parallel sub-agents:

- **codebase-pattern-finder**: Find 2-3 existing files that do similar things to the new code. Compare naming conventions, file organization, and API patterns.

- **codebase-analyzer**: Trace the new code's integration points. Verify it connects to existing components the same way other code does.

Every sub-agent prompt must include: "Compare the new code against existing patterns. Report differences factually — do not judge whether the difference is good or bad. The human decides."

Present findings:
```
## Pattern Compliance

Conventions followed:
- [convention]: [where it's followed]

Deviations found:
- [file:line]: [what differs from convention] — [existing pattern at file:line]
```

Do not label deviations as "wrong." Some are intentional improvements.

### Layer 3: Code Quality

Review all changed files for bugs, security issues, and quality problems.

1. **Gather changed files:**
   - Run `git diff --name-only HEAD~N` (where N = number of implementation commits)
   - Read each changed file in its entirety — not just the diff

2. **Check for real issues in these categories:**
   - Logic errors (off-by-one, incorrect conditionals, missing error handling, race conditions)
   - Security (injection vulnerabilities, XSS, insecure data handling, exposed secrets)
   - Performance (N+1 queries, inefficient algorithms, memory leaks)
   - Missing error handling at system boundaries

3. **Verify issues are real** before reporting:
   - Run relevant tests if available
   - Confirm type errors are legitimate
   - Check security concerns have actual attack surface

Do not report style preferences or documentation gaps. Focus on things that would break in production or create security risk.

Present findings:
```
## Code Quality

Issues found: [count]

### Critical (blocks commit)
- [file:line]: [issue] — [why it matters]

### High (should fix)
- [file:line]: [issue] — [why it matters]

### Medium (consider fixing)
- [file:line]: [issue] — [why it matters]
```

## Output

Combine all three layers into `$ARGUMENTS/validation.md`:

```markdown
# Validation Report

**Date:** [date]
**Status:** [pass | pass-with-warnings | fail]

## Functional Validation
[Layer 1 results]

## Pattern Compliance
[Layer 2 results]

## Code Quality
[Layer 3 results]

## Summary

### Must Fix Before Commit
- [critical and high issues from all layers]

### Warnings (Human Decision Needed)
- [deviations, medium issues, unmet non-critical outcomes]
```

**Status rules:**
- `fail` — any critical code quality issue OR any functional outcome not met. Wait for user to fix and re-run.
- `pass-with-warnings` — no critical issues but warnings exist. Present each warning. Do not treat warnings as resolved — user must explicitly confirm.
- `pass` — all outcomes met, no deviations, no issues.

Tell the user:
- If `fail`: "Fix the blocking issues and re-run `/qrspi/7b_validate $ARGUMENTS`"
- If `pass` or `pass-with-warnings` (after confirmation): "Next: run `/qrspi/8_pr $ARGUMENTS`"

## Rules

- Design is the spec. Functional validation compares against design's desired end state, not plan steps.
- Facts, not judgments. Report deviations neutrally — the human decides if they're intentional.
- Verify before reporting. Don't flag theoretical issues — confirm they're real.
- No duplicating work. Layer 2 handles patterns, Layer 3 handles bugs/security. Don't overlap.
- No fix suggestions in Layer 1 or Layer 2. Only Layer 3 may include fix guidance for confirmed bugs.

## When to Go Back

If functional validation reveals the implementation missed the design's intent entirely — not a small gap but a fundamental misunderstanding — suggest re-reading `design.md` and re-running `/qrspi/7_implement` rather than patching.
