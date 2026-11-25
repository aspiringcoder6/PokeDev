# Checklists — Change Impact Analysis

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* section
> of *Analyze Change Request Impact*). Operationalized quality criteria are
> `[Supplementary: IREB CPRE, ISO/IEC/IEEE 29148:2018]`.

## 1. Input completeness gate `[AI4RE]` (run before analyzing)

Ask for what is missing; if unavailable, record the gap as a stated limitation.

- [ ] Change request text is present and understood (no undefined key terms).
- [ ] Artifacts to be analyzed attached, each with an exact file name or path.
- [ ] **Traceability matrix** provided — otherwise hidden cross-artifact dependencies may
      be missed (analysis degrades to text matching; say so).
- [ ] **Architecture diagram and system boundary definition** provided — otherwise
      impacted modules/systems/interfaces are guesswork.
- [ ] **Glossary and business rule document** provided — otherwise business rules risk
      being treated as mere wording.
- [ ] **Interface descriptions, class diagrams, service specifications** provided —
      otherwise service-level logic and API contracts behind UI/text changes stay invisible.
- [ ] Sensitive-data reminder given if artifacts contain confidential business or customer
      data and an external AI service is involved.

## 2. Impact coverage sweep `[AI4RE]` (from the logical-vs-structural mitigation checklist)

For every change request element, explicitly check each category — "no impact" is a
finding too:

- [ ] **UI** — screens, mockups, labels, error/help texts, accessibility, localization
- [ ] **Service / logic** — validators, business services, rule engines
- [ ] **Data model** — entities, attributes, enumerations, derived values, persistence
- [ ] **API** — contracts, payloads, versioning
- [ ] **Integration** — connected/downstream systems, interface partners
- [ ] **Reports** — reporting, logging/audit, monitoring, analytics
- [ ] Plus documentation artifacts per hit: requirements, use cases, diagrams
      (UC/UML/flow), test specifications, user-facing content.

## 3. Per-impact row quality gate `[Supplementary: IREB CPRE / ISO 29148]`

Check each row of the impact table; every "no" must be fixed or logged as an open question.

- [ ] **Grounded** — source cited with exact file name/path; information type named
      (given input, missing artifacts, connected systems, …). `[AI4RE]`
- [ ] **Located** — exact edit location given (requirement ID, section, node label,
      method name), not just the document. `[AI4RE]`
- [ ] **Classified** — type of impact stated (e.g. functional rule change, UI removal,
      model change, interface contract check, potential side effect).
- [ ] **Actionable** — proposed action is concrete enough to execute or estimate; where
      useful, includes proposed new wording.
- [ ] **Owned** — responsible person/department named if known, or marked as a suggestion.
- [ ] **Risk-annotated** — dependencies, risks or validation needs stated (or explicitly
      "none").
- [ ] **Consistency-preserving** — the action leaves no orphaned references, contradicting
      texts or dangling flow steps behind (e.g. removed use case still referenced elsewhere).

## 4. Business-rule sensitivity check `[AI4RE]`

- [ ] Every changed statement examined: is it a legal/compliance-critical constraint
      rather than cosmetic wording?
- [ ] Rule changes flagged for validation with Product Owner or Legal/Compliance — never
      classified silently.
- [ ] Undefined rule terms (e.g. "dependent child") surfaced as definition gaps with an
      owner, not resolved by guessing.

## 5. Granularity and structure review `[AI4RE]`

- [ ] Findings categorized into fixed abstraction levels (e.g. requirement-level /
      artifact-level / system- and interface-level) — no mixing of high-level and
      fine-grained impacts in one list.
- [ ] Each CR element traceable to its impact rows (one element may map to many rows).
- [ ] Noise removed: duplicates merged, trivial non-impacts dropped, ownership per group
      clear.

## 6. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] Hidden dependencies: did I use trace links/architecture, or state that I could not?
- [ ] Business rules: any misclassification of a regulatory change as cosmetic?
- [ ] Logical vs. structural: does every UI/text/diagram impact have its backend
      counterpart checked? Developer confirmation of findings recommended?
- [ ] Granularity: consistent, planning-ready levels?
- [ ] Missing artifacts suggested (with proposed owners)?
- [ ] All assumptions prefixed `Assumption:`; open questions listed?
- [ ] Output labeled a **draft** requiring expert validation before the change is committed?
