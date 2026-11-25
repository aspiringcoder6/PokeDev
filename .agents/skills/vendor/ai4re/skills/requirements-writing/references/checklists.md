# Checklists — Requirements Writing

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* sections
> of the Formulate cluster). Quality-criteria operationalizations are
> `[Supplementary: IREB CPRE, ISO/IEC/IEEE 29148:2018, INVEST, SMART]`.

## 1. Single-requirement quality gate `[Supplementary: IREB CPRE / ISO 29148]`

Check each requirement; every "no" must be fixed or logged as an open question.

- [ ] **Unambiguous** — exactly one reading; no weak words (fast, easy, appropriate,
      user-friendly, etc., approx., possibly); quantities have units and bounds.
- [ ] **Complete** — actor, trigger/condition, action, object and qualifier present; error
      and boundary cases covered or explicitly out of scope.
- [ ] **Atomic** — one requirement per statement; no hidden "and/or" bundles.
- [ ] **Verifiable/testable** — a test could objectively pass/fail it; acceptance criteria
      or measures given.
- [ ] **Consistent** — terminology matches the synonym table; no contradiction with sibling
      requirements provided in context.
- [ ] **Traceable** — source (stakeholder/goal/parent requirement) identifiable; rationale
      for reformulation logged.
- [ ] **Comprehensible** — target audience can read it without insider knowledge beyond the
      glossary.
- [ ] **Necessary & feasible** — contributes to a stated goal; no invented gold-plating.
- [ ] **Actor explicit** — active voice; the system or role performing the action is named.
- [ ] **Self-contained** — no reference to other requirements, IDs, chapters or sections
      ("see REQ-12", "wie oben", "gemäß Kapitel 3", "analog zu Anforderung X"); the text is
      understandable on its own. External standards/laws may be named.
- [ ] **NFR classified** — non-functional requirements carry exactly one ISO/IEC 25010:2023
      category (or *Randbedingungen*), see [nfr-quality-model.md](nfr-quality-model.md).

## 2. User story gate — INVEST `[Supplementary: INVEST]`

- [ ] Independent — minimally coupled to other stories
- [ ] Negotiable — expresses intent, not implementation
- [ ] Valuable — benefit ("so that") is real and stated
- [ ] Estimable — scope clear enough to size
- [ ] Small — fits an iteration; splittable if not
- [ ] Testable — acceptance criteria are objective (Given/When/Then)

## 3. Goal gate — SMART `[AI4RE]` (referenced by the decompose-goals template)

- [ ] Specific · [ ] Measurable · [ ] Achievable · [ ] Relevant · [ ] Time-bound

## 4. Decomposition review `[AI4RE-adapted]` (from Decompose Requirement pitfalls)

- [ ] **Single abstraction level** — no mixing of business objective, feature and UI detail
      in one list.
- [ ] **Traceable contribution** — every sub-requirement demonstrably serves the parent;
      strategic intent and business value still visible.
- [ ] **No invented precision** — no benchmark (e.g. "99.999% uptime") that the input or
      the user did not sanction; such numbers are proposals marked `Assumption:`.
- [ ] **No silent gaps** — all nine ISO/IEC 25010:2023 categories plus *Randbedingungen*
      considered or explicitly excluded with a reason.
- [ ] **Accessibility** — system with UI, document output or media → accessibility block
      present (WCAG AA, applicable EN 301 549 clauses; Austrian public sector: WZG, proof
      and statement obligations).
- [ ] **Architecture-aware** — no sub-requirement contradicts stated technical or
      organizational constraints.
- [ ] **Assumptions & Scope block present**, **Risks / Points to Clarify present**.

## 5. Synonym table review `[AI4RE]`

- [ ] Every primary term and synonym occurs in the source document (grounding rule).
- [ ] No false equivalences — similar ≠ interchangeable (e.g. "sterile" vs. "clean" in a
      medical context).
- [ ] Register fits the audience (e.g. "assist" vs. "help" in clinical protocols).
- [ ] Ambiguous terms with multiple meanings flagged in Notes (e.g. "discharge", "ICD").
- [ ] No overly broad/vague synonyms; no trivial entries.
- [ ] Alphabetical order; markdown table format correct.
- [ ] Expert validation recommended in the closing note.

## 6. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] Input was ambiguous → did I ask, or mark assumptions? (Never silently interpret
      fuzzy goals.)
- [ ] Domain-specific or regulatory nuance involved → did I recommend SME review?
- [ ] Did I overfit to a common pattern that may not suit this domain?
- [ ] Is the output labeled a **draft** requiring human review?
- [ ] Rationale for substantive changes logged (reformulation traceability)?
