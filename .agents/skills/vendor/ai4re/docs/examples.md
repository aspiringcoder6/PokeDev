# Examples

Two levels of examples exist in this repository:

1. **Per-skill examples** — every skill's `references/examples.md` contains one worked
   example condensed from the AI4RE guide `[AI4RE]` plus several new domain examples
   `[AI4RE-adapted]` (automotive, medical, banking, e-commerce, embedded, cloud, agile,
   AI systems).
2. **End-to-end scenarios** — the [examples/](../examples/) directory walks through
   multi-skill workflows orchestrated by `ai4re-master`.

## End-to-end scenarios

| Scenario | Domain | Workflow | Skills exercised |
|---|---|---|---|
| [software-project](../examples/software-project/README.md) | SaaS fleet management | W1 greenfield: idea → reviewed spec | preparation → transcription → extraction → writing → verification → traceability |
| [automotive](../examples/automotive/README.md) | ADAS / embedded ECU | W4 change management + W5 reverse engineering | translation (code→req) → writing → verification → traceability → change-impact |
| [medical-device](../examples/medical-device/README.md) | Infusion pump (IEC 62304 context) | W3 spec audit + W6 stakeholder validation | writing (synonyms) → verification → translation (plain language) → validation (wireframe) |
| [agile-banking](../examples/agile-banking/README.md) | Retail banking, Scrum/SAFe | W2 transcript → backlog | transcription → extraction → writing (INVEST stories) → translation (test cases) → traceability (tags) |

Each scenario README shows: the user request, the master skill's classification and plan,
abridged artifacts per step, the shared context (glossary, assumptions, open questions)
flowing between steps, and the consolidated final deliverable.

## Quick usage examples (single skill)

- *"Rewrite this requirement as a user story with acceptance criteria."* →
  `requirements-writing`, use case Specify Requirement.
- *"Here is a photo of our whiteboard session — digitize it."* →
  `elicitation-transcription`, Transcribe Whiteboard Images.
- *"Generate test cases for these five requirements."* → `requirements-translation`,
  Generate Test Cases.
- *"Do these two diagrams contradict each other?"* → `requirements-verification`,
  Check Model Consistency.
- *"We want to change the tariff calculation — what's affected?"* →
  `change-impact-analysis`.
