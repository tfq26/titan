# Cross-Project Context Policy

Status: Active

This policy governs how agents look up context from another project without
confusing project-local truth.

## When To Look Up Another Project

Cross-project context is appropriate when:

- The current project faces a problem that another project has already solved.
- The solution pattern is documented in a portable-feature note in the shared
  vault.
- The agent has been explicitly asked to search for reusable patterns.

Cross-project context is NOT appropriate when:

- The agent is unsure about the current project's own code ("let me check how
  Ahamkara does it" is not a substitute for reading the current project's code).
- The goal is to copy code from another project.

## How To Look Up

1. Search the shared vault `patterns/` index first for relevant portable
   features, traps, or review heuristics.
2. If not found in patterns, search the other project's vault (read-only).
3. Load relevant portable-feature notes, decision records, or system maps.
4. Tag all external findings as `source: external` in working context.
5. Treat other-project findings as hypotheses — validate against current-project
   code, tests, and constraints.

## Rules

- Never write to another project's vault during a cross-project lookup.
- Never assume another project's implementation is correct for the current
  project.
- Always adapt patterns to current-project conventions, dependencies, and
  constraints.
- Portable-feature notes in the shared vault must include `project_specific`
  and `reusable_parts` sections so the adapter knows what to keep and what to
  change.

## Portable Feature Notes

Use `templates/portable-feature.md` to extract a reusable pattern from a project
into the shared vault. Portable feature notes should answer:

- What problem did the feature solve?
- What design constraints mattered?
- What implementation pattern worked?
- What mistakes happened?
- What validation was required?
- What was project-specific vs portable?

## Related

- `templates/portable-feature.md` — template for extracting patterns
- `patterns/INDEX.md` — searchable index of extracted patterns
