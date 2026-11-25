# Checklists — Requirements Translation

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* sections
> of the Translate cluster). Quality-criteria operationalizations are
> `[Supplementary: IREB CPRE, ISO/IEC/IEEE 29148:2018, ISO/IEC/IEEE 29119, Mermaid/PlantUML]`.

## 1. Universal translation gate `[AI4RE-adapted]`

Run on every output of this skill; every "no" must be fixed or logged as an open question.

- [ ] **Meaning preserved** — no intent changed, added or removed; conditions, constraints
      and obligation levels (must/should/can) intact.
- [ ] **Traceable** — every output element maps to an input element; inferred/suggested
      content is separated and marked (`Assumption:` / labeled hypothesis).
- [ ] **Grounded** — no hallucinated details where the source is silent; gaps are named,
      not filled.
- [ ] **Audience declared and served** — target group/tool/standard was confirmed, and the
      output's language and detail level match it.
- [ ] **Validation note present** — assumptions, gaps, open questions listed at the end.
- [ ] **Draft label** — output marked as a draft requiring expert validation.

## 2. Model-from-text review `[AI4RE]` (from Generate Model From Text pitfalls)

- [ ] **Context sufficient** — domain-specific context was in the prompt or requested;
      domain-expert review recommended for the generated diagram.
- [ ] **Input chunked** — large or complex input broken into short, structured chunks
      (e.g. lists of user stories) before generation; consistent input format.
- [ ] **Syntax valid** — PlantUML/Mermaid/BPMN XML/SysML code checked; on error, the error
      was fed back and the code regenerated (self-correction loop) before delivery.
      `[Supplementary: Mermaid/PlantUML]` Validate against the target renderer's syntax.
- [ ] **No overgeneration** — element and attribute counts justified by the source text;
      no inflated completeness.
- [ ] **Grouping rationale given** — requirement groups explained; user chose the group.
- [ ] **Element table present** — diagram elements listed with type and mapped
      requirement(s).
- [ ] **Importable** — textual notation deliverable as-is into modeling tools.

## 3. Text-from-model review `[AI4RE]` (from Generate Text From Model pitfalls)

- [ ] **No semantic loss** — multiplicities, guards, triggers, alt/opt/loop fragments and
      constraints carried into the text, not dropped or softened.
- [ ] **Input fidelity checked** — screenshots/PDFs without machine-readable metadata
      flagged as a risk; textual model input requested where possible.
- [ ] **Untranslatable cues flagged** — colors, icons, stereotypes that flatten in text are
      named in the validation note.
- [ ] **No hallucinated behavior** — nothing in the requirements that the model does not
      show; interpretations (e.g. a service's assumed responsibility) labeled as such.
- [ ] **Element extraction precedes requirements** — traceable two-step output.

## 4. Plain-language review `[AI4RE]` (from Explain Requirements pitfalls)

- [ ] **No oversimplification** — conditions and constraints survive ("only if role X"
      stays conditional).
- [ ] **Modal verbs intact** — "must" never became "should"/"can"; normative power kept.
- [ ] **Terms explained, not eliminated** — e.g. "authentication" → "log in with username
      and password", not silently dropped.
- [ ] **Risks/compliance not downplayed** — security, privacy, legal statements keep their
      weight.
- [ ] **Format kept** — binding statements not recast as user stories or loose goals.
- [ ] **No unverified assumptions/bias** — nothing added from "common sense".
- [ ] **Audience specified** — stakeholder group named; language calibrated to it (e.g.
      executive vs. frontline).
- [ ] **No fluff** — no "enhances efficiency"-style phrases without concrete linkage;
      trade-offs/limitations indicated where relevant; themes summarize impact, not
      feature lists; nuances survive grouping.

## 5. Persona review `[AI4RE]` (from Generate Persona pitfalls)

- [ ] **One persona, grounded** — exactly one profile, strictly based on the provided
      input.
- [ ] **Structure complete** — all eight fields (name … expectations towards the system).
- [ ] **No stereotypes or clichés** — traits derive from the data, not from demographic
      defaults.
- [ ] **Hypotheses labeled** — anything not directly supported by the input marked for
      later validation.
- [ ] **Concise** — plain text, under 200 words.
- [ ] **Review recommended** — validation with stakeholders, UX experts or domain
      specialists explicitly suggested.

## 6. Test-case review `[AI4RE]` (from Generate Test Cases pitfalls)

- [ ] **Input quality checked** — vague/ambiguous requirements flagged before deriving
      tests (they produce misaligned test cases).
- [ ] **Type coverage** — positive, negative and edge cases present where applicable; each
      row typed.
- [ ] **Traceability** — every test case carries the tested requirement's ID.
- [ ] **Testable rows** `[Supplementary: ISO/IEC/IEEE 29119]` — each row has a concrete
      input/precondition and an objectively checkable expected output.
- [ ] **Coverage gaps named** — untested types (security, performance, usability, …)
      listed; output declared a supplement to, not a replacement for, test design.
- [ ] **Domain review** — domain experts recommended for edge cases and business rules.
- [ ] **Completeness under volume** — large sets split into sub-tasks; no silently
      truncated table.

## 7. Code-to-requirements review `[AI4RE]` (from Generate Requirements From Source Code pitfalls)

- [ ] **Context limits stated** — missing invocation context, dependencies or architecture
      named; their impact on confidence stated.
- [ ] **No overgeneralization** — no requirement whose scope exceeds the visible code
      without an `Assumption:` mark.
- [ ] **NFR honesty** — non-functional requirements only where the code evidences them;
      otherwise the gap is stated, not padded.
- [ ] **NFR classified** — each NFR grouped under one ISO/IEC 25010:2023 category (or
      *Randbedingungen*) with its sub-characteristic.
- [ ] **Intent disambiguated** — helper/utility logic not promoted to user-facing
      requirements.
- [ ] **Traceability note present** — each requirement points to the code that informed
      it; weak traceability (snippet input) flagged.
- [ ] **Implementation-independent wording** — requirements describe *what*, not the code's
      *how*.

## 8. Generated-requirement quality gate `[Supplementary: IREB CPRE / ISO 29148]`

Apply to requirements produced by use cases 2 and 6:

- [ ] Unambiguous — one reading; no weak words; quantities with units and bounds.
- [ ] Complete — actor, trigger/condition, action, object present.
- [ ] Atomic — one requirement per statement.
- [ ] Verifiable — objectively testable.
- [ ] Consistent — terminology uniform across the generated set and with the source model
      or code identifiers.
