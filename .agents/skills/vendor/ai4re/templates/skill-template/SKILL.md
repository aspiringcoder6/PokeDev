---
name: skill-name-here
description: >
  <What the skill does> according to <source> (cluster "<Cluster>"). Use when the user
  wants to <task 1>, <task 2>, or <task 3>. Triggers include: "<trigger phrase>",
  "<trigger phrase>". (Max 1024 chars; third person; answers WHAT and WHEN.)
version: 0.1.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: <Elicitation | Documentation | Validation | Management>
  ai4re-cluster: <Cluster, or "—" for skills beyond the guide>
  ai4re-use-cases: [<Exact Use Case Title>, ...]
---

# Skill Name Here

One-line summary: turns <input> into <output>.

## Provenance

`[AI4RE]` / `[AI4RE-adapted]` / `[Supplementary: <source>]` — state which AI4RE use cases
this skill implements and which content comes from other standards. For skills covering a
gap in the guide (see knowledge base §8), say so explicitly.

## When to use / when not to use

**Use when the user wants to:**
- <situation>

**Do not use when:**
- <situation> → `<sibling-skill>` (point every anti-trigger to the right skill)

## Roles

- **Claude acts as:** <expert persona per the AI4RE template>
- **Typical users:** <requirements engineers, business analysts, …>

## Core workflow

1. **Intake.** Identify which use case applies.
2. **Establish context.** Domain, system, target format, quality standard; resolve every
   template variable or ask.
3. **Clarify or assume.** Ask targeted questions on ambiguity; otherwise prefix guesses
   with `Assumption:`. Remind about sensitive data when relevant.
4. **Execute** the use-case procedure (below) with the matching template from
   [references/templates.md](references/templates.md).
5. **Self-review.** Run [references/checklists.md](references/checklists.md) against your
   own output; unfixable gaps become open questions.
6. **Deliver.** Requested format + assumptions, open questions, risks + draft label.

## Use cases

### 1. <Use Case Title> `[AI4RE]`

1. <step>
2. <step>

Template: *<Template name>* in [references/templates.md](references/templates.md).

## Output formats

- <named format with structure>

## Quality gates

<Which IREB/ISO criteria this skill enforces, with source tags.>

## Self-review protocol

- <scan 1>
- <scan 2>

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing the use cases |
| [references/checklists.md](references/checklists.md) | Self-review; quality check requests |
| [references/examples.md](references/examples.md) | User wants a sample |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining/adapting the method |
| [references/system-prompt.md](references/system-prompt.md) | Standalone prompt for other AI tools |
