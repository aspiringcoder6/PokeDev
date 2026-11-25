# AI4RE Claude Skills

**Modular Claude Skills that turn Claude into a requirements engineering assistant
following the IREB standard** — a structured, extensible toolbox for the whole RE
lifecycle, built on the official [IREB AI4RE Prompt Guide](https://ireb.atlassian.net/wiki/spaces/airebpromptguide/overview).

> Unofficial community project. Not endorsed by or affiliated with IREB e.V. — see
> [NOTICE.md](NOTICE.md) for full attribution and the content-provenance rules.

## Project goal

The AI4RE Prompt Guide provides prompt templates for 23 RE use cases. This repository
transfers them from copy-paste prompts into **reusable, self-reviewing skills**: each skill
encodes the guide's workflows, quality criteria, pitfalls and templates so Claude applies
them autonomously — asking clarifying questions, marking assumptions, validating its own
output against IREB quality gates, and always delivering drafts for expert validation.

## Architecture

The skill layout mirrors the guide's own taxonomy — 4 IREB core activities → 9 activity
clusters → 23 use cases — plus a supervisor:

```
                        ┌─────────────────────┐
                        │     ai4re-master     │  classifies, plans, routes,
                        │  (supervisor skill)  │  carries context, reviews
                        └──────────┬──────────┘
      ┌──────────────┬─────────────┼──────────────┬──────────────┐
  Elicitation    Documentation             Validation         Management
      │              │                         │                  │
  elicitation-   requirements-writing      requirements-      change-impact-
  preparation    (Formulate)               validation         analysis (Align)
  (Explore)                                (Validate)
  elicitation-   requirements-translation  requirements-      requirements-
  transcription  (Translate)               verification       traceability
  (Transcribe)                             (Verify)           (Assign)
  requirements-
  extraction
  (Extract)
```

Details: [docs/architecture.md](docs/architecture.md) ·
[docs/skill-overview.md](docs/skill-overview.md)

## Skills

| Skill                                                                  | IREB activity | AI4RE use cases                                                                                                                                                    |
| ---------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [ai4re-master](skills/ai4re-master/SKILL.md)                           | all           | routes all 23; plans multi-skill workflows                                                                                                                         |
| [elicitation-preparation](skills/elicitation-preparation/SKILL.md)     | Elicitation   | Introduce a New Domain · Identify Stakeholders · Prepare Interview · Plan Workshop                                                                                 |
| [elicitation-transcription](skills/elicitation-transcription/SKILL.md) | Elicitation   | Refine Transcription · Transcribe Whiteboard Images                                                                                                                |
| [requirements-extraction](skills/requirements-extraction/SKILL.md)     | Elicitation   | Identify Requirements                                                                                                                                              |
| [requirements-writing](skills/requirements-writing/SKILL.md)           | Documentation | Specify Requirement · Decompose Requirement · Generate Synonym Table                                                                                               |
| [requirements-translation](skills/requirements-translation/SKILL.md)   | Documentation | Generate Model From Text · Generate Text From Model · Explain in Simple Language · Generate Persona · Generate Test Cases · Generate Requirements From Source Code |
| [requirements-validation](skills/requirements-validation/SKILL.md)     | Validation    | Generate Wireframe                                                                                                                                                 |
| [requirements-verification](skills/requirements-verification/SKILL.md) | Validation    | Analyze Requirements Consistency · Check Model Consistency · Compare Specification With Source Code                                                                |
| [change-impact-analysis](skills/change-impact-analysis/SKILL.md)       | Management    | Analyze Change Request Impact                                                                                                                                      |
| [requirements-traceability](skills/requirements-traceability/SKILL.md) | Management    | Tag Requirements · Trace Requirements                                                                                                                              |

## Installation

**As a Claude Code plugin (recommended):**

```
/plugin marketplace add chrsbrmr/ai4re-skill
/plugin install ai4re
```

**Manual (personal skills):** copy the directories under `skills/` into `~/.claude/skills/`
(or `.claude/skills/` inside a project).

**Outside Claude Code:** every skill ships a standalone system prompt in
`references/system-prompt.md` for use with any LLM tool.

Details: [docs/installation.md](docs/installation.md)

## Usage

Skills activate automatically when a request matches their description. Examples:

- _"Here is our workshop transcript — extract the requirements and write user stories."_
  → `ai4re-master` plans: transcription refinement → extraction → writing.
- _"Rewrite this requirement as a user story with acceptance criteria."_
  → `requirements-writing`, directly.
- _"Does our spec contradict itself anywhere?"_ → `requirements-verification`.

Every skill asks clarifying questions when input is ambiguous, marks assumptions
(`Assumption:`), self-reviews against IREB quality criteria and ends with open questions
and risks. More walkthroughs: [docs/examples.md](docs/examples.md) and
[examples/](examples/).

## Extensibility

New RE skills follow the conventions in
[docs/skill-authoring-guide.md](docs/skill-authoring-guide.md); a ready-to-copy scaffold is
in [templates/skill-template/](templates/skill-template/). See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Provenance & license

Every section in every skill is tagged: `[AI4RE]` (from the guide), `[AI4RE-adapted]`
(guide-based, restructured) or `[Supplementary: <source>]` (other standards — IREB CPRE,
ISO/IEC/IEEE 29148, INVEST, SMART, EARS). Rules: [NOTICE.md](NOTICE.md). Original content
is MIT-licensed: [LICENSE](LICENSE).
