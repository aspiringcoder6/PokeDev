# Checklists — Requirements Verification

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* and
> accuracy sections of the Verify cluster). Operationalized consistency-check criteria
> are `[Supplementary: ISO/IEC/IEEE 29148:2018, IREB CPRE Glossary]`.

## 1. Findings quality gate `[AI4RE]`

Check every finding before delivery; every "no" means fix or delete the finding.

- [ ] **Evidenced** — cites verbatim requirement text, exact element names, or a
      concrete code reference (file + element) from the input. No evidence → no finding.
- [ ] **Unaltered quotes** — requirement text quoted exactly, never paraphrased.
- [ ] **Single categorization** — each pair/element reported once, in the most
      appropriate category; category and subtype named precisely.
- [ ] **Actionable suggestion** — 2–3 sentences, tailored to the specific pair/finding,
      explaining how to resolve the issue and why it matters.
- [ ] **No noise** — no individual, unrelated requirements listed; no trivial or
      speculative findings.
- [ ] **Honest verdicts** (spec-vs-code) — Match / Partial / Missing / Extra assigned
      per evidence; "not visible in the provided files" is Partial with a caveat, not
      Missing.

## 2. Consistency-check criteria `[Supplementary: ISO/IEC/IEEE 29148:2018, IREB CPRE]`

What "consistent" means operationally — scan the artifact set for each dimension:

- [ ] **Logical consistency** — no two statements can both be satisfied; no
      condition/exception contradicts another's rule.
- [ ] **Value consistency** — numeric thresholds, ranges and tolerances compatible;
      identical concepts use identical units and measurement bases.
- [ ] **Terminological consistency** — one term per concept; no synonym drift ("client"
      vs. "customer"), no homonym collisions; actor/role names uniform.
- [ ] **Modality consistency** — shall/should/may (or must/can) used uniformly for the
      same obligation level; priority attributes do not contradict wording.
- [ ] **Temporal/sequence consistency** — prescribed orders, lifecycles and state
      transitions never violated by other requirements, diagrams or code paths.
- [ ] **Structural consistency** (models) — signatures, datatypes and multiplicities
      identical across views; static constraints not violated by dynamic behavior.
- [ ] **Boundary consistency** — system boundary and stakeholder groups identical
      across all views; nothing is inside the system in one artifact and outside in
      another.
- [ ] **Reference consistency** — cross-references, versions and IDs point to current,
      existing targets (no version drift).
- [ ] **Set-level completeness** — combinations of requirements do not imply a missing
      companion requirement or coverage hole; NFRs do not contradict functionality.

## 3. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] **No overreliance framing** — report states that AI may have wrongly identified
      inconsistencies and cannot be relied on to find all of them; human oversight
      required.
- [ ] **Consistency ≠ correctness** — caveat included: perfectly consistent artifacts
      can still describe the wrong system; this is cross-view verification, not
      validation.
- [ ] **Abstraction levels respected** — before flagging duplicates across documents,
      abstraction level / document / trace attributes were checked or requested;
      legitimate system-vs-component similarity not reported as duplication.
- [ ] **Scale handled** — for large inputs, chunking or iterative re-runs proposed
      ("re-run until no new issues"); for model comparisons, a fresh session per
      comparison iteration recommended; degraded coverage disclosed.
- [ ] **Context gaps disclosed** (spec-vs-code) — requirements irrelevant to the given
      code identified as such; NFRs (e.g. safety, security) flagged as unverifiable
      from the provided implementation where applicable.
- [ ] **Format fits structure** — if code maps to multiple hierarchically linked
      requirements, the flat table's limits are stated and a hierarchical/matrix view
      offered.
- [ ] **Coverage statement present** — what was compared, what was skipped, which
      files/diagrams/ranges were not provided.
- [ ] **Draft label** — output marked as a draft requiring expert review; sensitive
      inputs (production code, regulated specs) triggered a confidentiality reminder.

## 4. Use-case-specific spot checks `[AI4RE-adapted]`

**Requirements consistency:**
- [ ] All requirements have IDs (existing preserved, `REQ-###` generated in reading
      order for the rest).
- [ ] Pairwise comparison covered the whole set (or the skipped range is disclosed).
- [ ] Empty result rendered as an explicit "no issues detected" section.

**Model consistency:**
- [ ] Diagram types identified before comparison; elements parsed per UML metamodel.
- [ ] Naming, signatures/types, multiplicities-vs-behavior, lifecycle rules, and
      system boundary/stakeholders all checked.
- [ ] Every suggestion offers resolution alternatives where intent is ambiguous
      ("if same concept … / if different concept …").

**Spec vs. source code:**
- [ ] Every specification item appears exactly once in the table with a verdict.
- [ ] Extra (unspecified) behavior in the code reported, not only missing behavior.
- [ ] Summary buckets present: Good Matches / Partially Fulfilled / Missing
      Implementations, plus recommendations.
