# Skill Authoring Guide

This guide defines the mandatory conventions for every skill in this repository. Follow it
when creating a new skill or modifying an existing one. The reference implementation is
[`skills/requirements-writing/`](../skills/requirements-writing/SKILL.md) — when in doubt, mirror it.

## 1. Directory layout

Every skill is a directory under `skills/` using a **kebab-case noun phrase** (max 64 chars):

```
skills/<skill-name>/
├── SKILL.md                     # Entry point: metadata + core instructions (< 500 lines)
└── references/
    ├── templates.md             # AI4RE prompt templates, adapted for skill use
    ├── checklists.md            # Quality & self-review checklists
    ├── prompt-patterns.md       # Prompt techniques used by this skill
    ├── examples.md              # Worked examples across domains
    └── system-prompt.md         # Standalone system prompt (for use outside Claude Code)
```

`SKILL.md` follows the official [Claude Agent Skills](https://code.claude.com/docs/en/skills)
format. Metadata lives in its YAML frontmatter — there is deliberately **no separate
`metadata.yaml`** (see [architecture.md](architecture.md), decision D3).

## 2. SKILL.md frontmatter

```yaml
---
name: <skill-name>                # must equal the directory name
description: >
  <What the skill does> + <when Claude should use it>. Mention concrete trigger
  phrases and artifacts (e.g. "user story", "interview transcript"). Max 1024 chars.
version: 1.0.0                    # SemVer, bump per CHANGELOG rules
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: <Elicitation | Documentation | Validation | Management>
  ai4re-cluster: <Explore | Transcribe | Extract | Formulate | Translate | Validate | Verify | Align | Assign>
  ai4re-use-cases: [<Use Case Title>, ...]   # exact titles from the AI4RE Prompt Guide
---
```

The `description` is the **only** thing Claude sees before deciding to load the skill.
It must answer both *what* and *when* in the third person ("Formulates…", "Use when…").

## 3. SKILL.md body — mandatory sections, in this order

| # | Section | Content |
|---|---------|---------|
| 1 | Title + one-line summary | What the skill turns into what |
| 2 | **Provenance** | Which AI4RE use cases it implements; which content is supplementary (see §5) |
| 3 | **When to use / when not to use** | Trigger situations; anti-triggers with pointers to sibling skills |
| 4 | **Roles** | The expert role Claude adopts; typical user roles served |
| 5 | **Core workflow** | Numbered step-by-step process: intake → context clarification → execution → self-review → output. Clarifying questions and assumption-marking are mandatory steps, not options |
| 6 | **Use cases** | One subsection per AI4RE use case with its specific procedure and a pointer to the template in `references/templates.md` |
| 7 | **Output formats** | Explicit, named formats (tables, user stories, models, …) |
| 8 | **Quality gates** | The IREB/ISO quality criteria this skill enforces |
| 9 | **Self-review protocol** | Checks the skill runs on its *own* output before presenting it |
| 10 | **References** | Table: which reference file to load in which situation |

Keep `SKILL.md` under ~500 lines. Anything bulky (full templates, long checklists,
multi-page examples) belongs in `references/` — Claude loads those on demand
(progressive disclosure).

## 4. Behavioral rules every skill must encode

Derived from the AI4RE Prompt Guide's general cautions and pitfall sections:

1. **Draft, not decision** — always present output as a draft requiring expert validation.
2. **Ask before assuming** — when input is ambiguous or incomplete, ask targeted clarifying
   questions; if proceeding anyway, mark every assumption explicitly (`Assumption:` prefix).
3. **Ground on provided artifacts** — never invent domain facts; separate *extracted from input*
   from *suggested/inferred* content.
4. **Self-validate** — run the skill's checklist against the output; iterate until it passes
   or the gaps are listed as open questions.
5. **Flag risks and open questions** — every deliverable ends with open questions,
   assumptions, and risk callouts (if any).
6. **Sensitive data caution** — remind users not to feed confidential data into external
   AI services when the context suggests they might.

## 5. Source attribution (mandatory)

It must always be recognizable which content is based on the IREB AI4RE Prompt Guide and
which comes from supplementary standards. Use these tags in section headers or as a
line directly under a heading:

- `[AI4RE]` — taken from the IREB AI4RE Prompt Guide (adaptation limited to formatting).
- `[AI4RE-adapted]` — based on the guide, restructured or extended for skill use.
- `[Supplementary: <source>]` — not from AI4RE; name the source, e.g.
  `[Supplementary: IREB CPRE Glossary]`, `[Supplementary: ISO/IEC/IEEE 29148:2018]`.

Every `templates.md` starts with a provenance header linking the original guide page.

## 6. Writing style

- English, active voice, imperative mood for instructions ("Identify key terms", not
  "Key terms should be identified").
- Address Claude directly — a skill is an instruction set, not an essay.
- No marketing language. No duplicated content between SKILL.md and references.
- Tables for enumerable facts; prose for reasoning.
- Variables in templates use `[SQUARE_BRACKETS]`, exactly as in the AI4RE guide.

## 7. Checklist for new skills

- [ ] Directory + `SKILL.md` + all five reference files exist
- [ ] Frontmatter valid: `name` = directory, description answers *what + when*
- [ ] All 10 body sections present, in order
- [ ] All 6 behavioral rules encoded in the workflow
- [ ] Every section carries a source tag (§5)
- [ ] Examples cover ≥ 3 distinct domains
- [ ] Skill registered in `docs/skill-overview.md` and the master skill's routing table
      (`skills/ai4re-master/references/routing.md`)
- [ ] `CHANGELOG.md` entry added

A ready-to-copy scaffold lives in [`templates/skill-template/`](../templates/skill-template/).
