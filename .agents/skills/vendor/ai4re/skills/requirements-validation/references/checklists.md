# Checklists — Requirements Validation

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* section
> of *Generate Wireframe*). Operationalized validation-readiness criteria are
> `[Supplementary: IREB CPRE]`.

## 1. Grounding & derivation gate `[AI4RE]`

Run against every generated wireframe; every "no" must be fixed or logged as an open
question.

- [ ] **Sole source of truth fixed** — exactly one input (requirements *or* UI
      specification) declared as primary source before generation.
- [ ] **Every screen derived** — each screen and feature traces to an explicit statement in
      the source; nothing added that is not explicitly supported.
- [ ] **No invented navigation** — no dashboards, menus, overview pages, quicklinks or
      global search that the input does not explicitly support. ("Necessity" is
      interpretative — the model tends to close gaps subtly via information architecture.)
- [ ] **No style contamination** — design context (style guides, screenshots) influenced
      look only; no structural patterns (hamburger menu, language toggle, global search)
      adopted from it as if they were requirements.
- [ ] **Gaps stayed visible** — inconsistencies, redundancies and unaddressed edge cases in
      the input are surfaced (ambiguity highlights), not silently smoothed over. A
      polished wireframe over inconsistent requirements creates a misleading sense of
      confidence.

## 2. Annotation & completeness gate `[AI4RE]`

Applies when the corresponding optional rules (3–6) are active — the skill's recommended
default is all of them.

- [ ] **States** — every top-level screen has empty, loading and error states, marked with
      a light yellow background (or `[STATE: …]` blocks in text formats).
- [ ] **Traceability tags** — each derived UI element carries a small red tag
      (e.g. "Ref: US-1"); tags appear nowhere else.
- [ ] **Assumptions** — minimal, listed, max. 5, light yellow background / `Assumption:`
      prefix. More than 5 needed → the input is too thin; ask instead of assuming.
- [ ] **Ambiguities** — each ambiguous or contradictory statement highlighted with two
      alternative interpretations, not resolved unilaterally.
- [ ] **Format** — one self-contained HTML file, embedded CSS, no external libraries,
      clearly separated sections per screen (or the agreed text alternative).

## 3. Validation-session readiness `[Supplementary: IREB CPRE]`

Operationalized criteria for the artifact's fitness as a validation aid — not from AI4RE.

- [ ] **Right audience** — artifact matches the named target group's language, literacy and
      context of use.
- [ ] **Reviewable granularity** — mid-fidelity: concrete enough to provoke corrections,
      rough enough that stakeholders discuss requirements, not pixel aesthetics.
- [ ] **Feedback path** — each finding can be mapped back to a requirement via the
      traceability tags.
- [ ] **Coverage known** — it is stated which requirements are represented and which are
      not (e.g. non-UI requirements out of scope).
- [ ] **Validation ≠ verification** — the session checks stakeholder needs; internal
      consistency defects found on the way are handed to `requirements-verification`.

## 4. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] Did stakeholder discussion risk shifting from *requirements validation* to debates
      about information architecture? (Cause: invented navigation — remove it.)
- [ ] Did I treat the requirements repository as complete and consistent when it is not?
      (Flag, don't fill.)
- [ ] Did style material act as "direction only" in name but shape structure in fact?
- [ ] Is the artifact labeled a **draft validation aid**, not a committed design or a
      formally agreed feature set?
- [ ] Are assumptions, ambiguities and open questions listed at the end?
- [ ] Sensitive data: did I warn the user before requirements containing confidential
      material go to an external AI service?
