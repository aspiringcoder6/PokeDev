# Architecture

## Design principles

1. **Mirror the guide's taxonomy.** Skills map 1:1 to the AI4RE Prompt Guide's nine
   activity clusters (4 IREB core activities → 9 clusters → 23 use cases). Every guide
   update lands in exactly one skill; traceability to the source stays trivial.
2. **Skills, not prompts.** The guide ships copy-paste templates; this repository encodes
   the surrounding discipline — clarifying questions, assumption marking, grounding,
   self-review, draft labeling — so Claude applies them autonomously.
3. **Progressive disclosure.** `SKILL.md` holds the compact workflow (< 500 lines);
   templates, checklists, patterns, examples and standalone system prompts live in
   `references/` and load on demand. This respects context budgets and the official
   Agent Skills design.
4. **Provenance always visible.** Every section is tagged `[AI4RE]`, `[AI4RE-adapted]` or
   `[Supplementary: <source>]` — see [NOTICE.md](../NOTICE.md).
5. **Supervisor on top.** `ai4re-master` classifies fuzzy or multi-task requests, routes
   to specialized skills, chains them with shared context (glossary, assumptions log,
   open questions, traceability thread) and runs a cross-skill review.

## Skill granularity — why 9 + 1

- One skill per *use case* (23 skills) would fragment shared discipline and bloat the
  skill list; one monolith would defeat progressive disclosure and maintainability.
- One skill per *cluster* groups use cases that share roles, patterns and pitfalls
  (e.g. all three Formulate use cases negotiate formulation standards) — the guide's own
  clustering is the natural seam.

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Official Agent Skills format (`SKILL.md` + YAML frontmatter) | Direct compatibility with Claude Code, claude.ai and the Agent SDK |
| D2 | Cluster = skill; use case = SKILL.md subsection + template | See granularity above |
| D3 | No `metadata.yaml` per skill | Frontmatter *is* the metadata; a second file would drift. Extra fields (`ireb-activity`, `ai4re-cluster`, `ai4re-use-cases`) live under `metadata:` in frontmatter |
| D4 | `references/system-prompt.md` per skill | Makes every skill usable outside Claude Code (any LLM tool) |
| D5 | Repository doubles as plugin + marketplace (`.claude-plugin/`) | One-command installation |
| D6 | English content | Open-source/marketplace reach; skills work with German input regardless |
| D7 | Cluster "Asign" [sic] renamed "Assign" | Guide typo; original spelling documented in routing.md and knowledge base |
| D8 | Uncovered RE tasks (prioritization, negotiation, …) routed to "scope honesty" in the master skill | Never silently improvise beyond the guide; documented extension points |

## Component view

```
.claude-plugin/          plugin.json + marketplace.json (installation)
docs/                    architecture, knowledge base, authoring guide, overview,
                         installation, examples
skills/
  ai4re-master/          supervisor: routing.md, workflows.md + standard file set
  <9 specialized skills> SKILL.md + references/{templates, checklists,
                         prompt-patterns, examples, system-prompt}.md
templates/skill-template/  scaffold for new skills
examples/                end-to-end domain scenarios (multi-skill walkthroughs)
```

## Control flow (multi-task request)

```
user request
   └─ ai4re-master: classify (routing.md) → check preconditions → plan (workflows.md)
        → clarify once, centrally
        → execute steps: load skill SKILL.md → its workflow → its self-review
             ↳ shared context carried forward (glossary, assumptions, questions, traces)
        → cross-skill review (master checklists.md)
        → consolidated deliverable (draft + assumptions + open questions + risks)
```

Single-task requests trigger the specialized skill directly via its `description`; the
master stays out of the way.
