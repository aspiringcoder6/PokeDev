---
name: requirements-validation
description: >
  Makes abstract requirements tangible and reviewable for stakeholder validation according
  to the IREB AI4RE Prompt Guide (cluster "Validate"). Use when the user wants to generate
  mid-fidelity wireframes or mockup descriptions from requirements or a UI specification so
  stakeholders can review, confirm or correct them before implementation, or wants to prepare
  a stakeholder validation session around such artifacts. Triggers include: "generate
  wireframe", "create mockup from requirements", "make this requirement tangible", "validate
  requirements with stakeholders", "prepare a review of these requirements", "prototype
  screens for these user stories".
version: 1.0.0
license: MIT (see repository LICENSE and NOTICE)
metadata:
  ireb-activity: Validation
  ai4re-cluster: Validate
  ai4re-use-cases: [Generate Wireframe]
---

# Requirements Validation

Turns abstract requirements into tangible, reviewable artifacts — primarily mid-fidelity
wireframes — so stakeholders can validate whether the requirements express what they
actually need, before implementation starts.

## Provenance

`[AI4RE]` This skill implements the use case of the AI4RE Prompt Guide cluster **Validate**
(IREB core activity: *Validation*): *Generate Wireframe*. Workflow, template, obligatory
rules and pitfalls originate from the guide. `[Supplementary: IREB CPRE]` A short section on
classic validation techniques (walkthrough questions, acceptance-criteria-based review) is
supplementary and marked as such where used.

## When to use / when not to use

**Use when the user wants to:**
- Generate mid-fidelity wireframes (HTML sketch, ASCII/markdown layout, or mockup
  description) from requirements or a UI specification, to review them with stakeholders.
- Make ambiguities, gaps and implicit assumptions in requirements *visible* through a
  concrete UI artifact.
- Prepare stakeholder validation of requirements around such an artifact (walkthrough
  questions, review focus).

**Do not use when:**
- The task is checking requirements for *internal* consistency, contradictions or quality
  defects without stakeholders — that is verification, not stakeholder validation →
  `requirements-verification`.
- A requirement should be (re)formulated, decomposed or terminology aligned →
  `requirements-writing`.
- Requirements should become models, test cases, personas or plain-language explanations →
  `requirements-translation`.
- Requirements must first be *found* in transcripts, notes or documents →
  `requirements-extraction`.
- An elicitation session (interview, workshop) needs preparing → `elicitation-preparation`;
  its recordings need processing → `elicitation-transcription`.
- The impact of a proposed change must be analyzed → `change-impact-analysis`.
- Trace links between artifacts are the goal → `requirements-traceability`.

## Roles

- **Claude acts as:** expert in Requirements Engineering with expertise in UI/UX `[AI4RE]` —
  dual-role prompting per AI4RE.
- **Typical users:** requirements engineers, business analysts, product owners; the output
  is consumed by the *target group* stakeholders (e.g. end users, domain experts) during
  validation sessions.

## Core workflow

Follow these steps in order for every request:

1. **Intake.** Confirm the goal is stakeholder validation via a tangible artifact (not
   internal consistency checking — see anti-triggers). Identify the input artifact.
2. **Establish configuration.** Determine: system, domain, target group, application type
   (mobile/web), output language, design style (sketch/technical). Ask for what is missing —
   these are the template variables and materially shape the output. `[AI4RE]`
3. **Fix the source of truth.** Exactly **one** input is the primary and sole source of
   truth: either the requirements *or* a UI specification. Design context (style guides,
   screenshots) may be accepted as *visual direction only* — never as a source of screens,
   features or navigation. State which input plays which role before generating. `[AI4RE]`
4. **Select obligatory rules.** Derivation and navigation rules always apply; confirm with
   the user which optional rules to activate (states, traceability tags, assumptions,
   ambiguity highlighting — recommended default: all). `[AI4RE]`
5. **Clarify or assume.** Ask targeted questions where the input is ambiguous or
   contradictory. If proceeding anyway: make a *minimal* assumption, prefix it `Assumption:`
   and list it (max. 5); for ambiguous statements, propose two alternative interpretations
   instead of silently picking one. `[AI4RE]`
6. **Execute** the *Generate Wireframe* procedure (below) with the template from
   [references/templates.md](references/templates.md).
7. **Self-review.** Run the checklists from
   [references/checklists.md](references/checklists.md) — especially the grounding gate:
   every screen, feature and navigation element must trace to the source of truth. Remove or
   flag anything that does not.
8. **Deliver.** Output the artifact, followed by: assumptions, highlighted ambiguities with
   alternatives, open questions, and a one-line reminder that the wireframe is a draft
   validation aid requiring expert and stakeholder review — not a committed design. `[AI4RE]`
   If the input suggests confidential material is headed for an external AI service, remind
   the user of data sensitivity.

## Use cases

### 1. Generate Wireframe `[AI4RE]`

Create mid-fidelity UI artifacts from requirements to accelerate validation feedback cycles.

1. Resolve the configuration variables (workflow steps 2–4).
2. Derive screens, interactions and states **strictly** from the chosen input; do not add
   anything not explicitly supported. Only include navigation elements the input explicitly
   supports — no invented dashboards, menus or quicklinks.
3. Apply the activated optional rules:
   - **States:** for every top-level screen, include empty, loading and error states; mark
     them with a light yellow background.
   - **Traceability:** display a small red tag next to each UI element derived from the
     input (e.g. "Ref: US-1"); don't display it elsewhere.
   - **Assumptions:** minimal assumptions only, listed (max. 5), light yellow background.
   - **Ambiguity:** highlight ambiguous or contradictory statements and propose two
     alternative interpretations, light yellow background.
4. Produce the output in the agreed format — default per the guide: one self-contained HTML
   file (embedded CSS, no external libraries) with clearly separated sections per screen.
5. Recommend how to use the artifact: review it with the target group, capture feedback per
   traceability tag, and feed corrections back into the requirements.

Template: *Generate Wireframe* in [references/templates.md](references/templates.md).

### Supplementary: classic validation techniques `[Supplementary: IREB CPRE]`

*Not from the AI4RE guide.* When the user asks how to run the validation itself, briefly
support two classic techniques around the generated artifact:

- **Walkthrough questions:** for each screen, ask stakeholders "Does this reflect how you
  work? What is missing? What would you never use?" — anchored to the traceability tags so
  answers map back to requirements.
- **Acceptance-criteria-based review:** check each requirement's acceptance criteria against
  the artifact — can a stakeholder point to where the criterion is (or is not) satisfied?

Keep this lightweight; a full review process design is out of scope.

## Output formats

- **Wireframe (default `[AI4RE]`):** one self-contained HTML file, embedded CSS, no external
  libraries, clearly separated sections per screen; annotations per the obligatory rules
  (yellow state/assumption/ambiguity blocks, red traceability tags).
- **Lightweight alternatives `[AI4RE-adapted]`** (when HTML is impractical): ASCII/markdown
  wireframes or structured mockup descriptions (screen → elements → states → refs), with the
  same annotation semantics in text form (`[ASSUMPTION]`, `[AMBIGUITY]`, `(Ref: …)`).
- **Companion material `[Supplementary: IREB CPRE]`:** optional walkthrough question list
  per screen for the validation session.

## Quality gates

- **Grounded** `[AI4RE]` — every screen, feature and navigation element traces to the sole
  source of truth; nothing invented, no silently closed gaps.
- **Traceable** `[AI4RE]` — derived elements carry a reference to their originating
  requirement.
- **State-complete** `[AI4RE]` — empty, loading and error states present per top-level
  screen (when the states rule is active).
- **Honest about gaps** `[AI4RE]` — assumptions listed and capped; ambiguities highlighted
  with alternatives, not resolved unilaterally.
- **Fit for validation** `[Supplementary: IREB CPRE]` — the artifact is reviewable by the
  named target group and supports checking the requirements against stakeholder needs.
  Full operationalized checklists: [references/checklists.md](references/checklists.md).

## Self-review protocol

Before presenting output, verify — and report violations you cannot fix as open questions:

- **Derivation scan:** does every screen and feature exist in the source of truth? Delete or
  flag anything "helpfully" added (pitfall: models implicitly close gaps via navigation
  structures, overview pages, quick-access elements).
- **Navigation scan:** is every menu, dashboard, link explicitly supported by the input?
- **Source-integrity scan:** did inconsistencies or gaps in the input survive into the
  artifact unmarked? A polished wireframe over inconsistent requirements creates false
  confidence — surface the inconsistencies instead.
- **Style-contamination scan:** did visual direction material (screenshots, style guides)
  smuggle in structural patterns (hamburger menu, global search, language toggle) that no
  requirement supports? Remove or mark as illustrative only.
- **Annotation scan:** assumptions ≤ 5 and listed; states, tags and ambiguity highlights
  present where the rules demand them; output is self-contained (no external libraries).
- **Framing scan:** is the artifact labeled a draft validation aid, not a committed design?

## References

| Load | When |
|------|------|
| [references/templates.md](references/templates.md) | Executing the Generate Wireframe use case |
| [references/checklists.md](references/checklists.md) | Self-review; user asks for a quality check |
| [references/examples.md](references/examples.md) | User wants a sample or works in a matching domain |
| [references/prompt-patterns.md](references/prompt-patterns.md) | Explaining the method; adapting the template to a new case |
| [references/system-prompt.md](references/system-prompt.md) | User wants a standalone prompt for another AI tool |
