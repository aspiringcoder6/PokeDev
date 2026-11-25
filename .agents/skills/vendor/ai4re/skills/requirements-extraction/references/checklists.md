# Checklists — Requirements Extraction

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* section
> of *Identify Requirements*, cluster Extract). Quality-criteria operationalizations are
> `[Supplementary: IREB CPRE, ISO/IEC/IEEE 29148:2018]`.

## 1. Grounding & traceability gate `[AI4RE]`

The core promise of the extraction format. Every "no" must be fixed before delivery.

- [ ] **Reference present** — every candidate requirement has a quote from the input in
      its Reference column; no orphan candidates.
- [ ] **Reference verbatim** — the quote occurs in the input as written; condensed or
      spliced quotes ("…" joins) are marked as such.
- [ ] **Reference supports the candidate** — the quote actually expresses the need the
      candidate states, not merely a nearby sentence.
- [ ] **Duplicates merged transparently** — one candidate per need; merged duplicates cite
      all their source quotes.
- [ ] **Nothing invented** — no candidate the input does not support; suggestions and
      inferences are outside the table and marked as such.

## 2. Candidate quality gate `[Supplementary: IREB CPRE / ISO 29148]`

Extraction-level quality only — full formulation quality belongs to `requirements-writing`.

- [ ] **Atomic** — one requirement per row; no hidden "and/or" bundles from a single
      rambling statement.
- [ ] **Comprehensible** — a reader who was not in the session understands the candidate
      without insider knowledge beyond the input.
- [ ] **Intent-preserving** — the candidate says what the stakeholder meant; role and
      benefit are taken from the input, not decorated.
- [ ] **Necessary** — the candidate plausibly serves the stated business goals; relevance
      doubts are flagged, not silently resolved.

## 3. Classification & grouping review `[AI4RE]` (from the *Over-Categorization* pitfall)

- [ ] **No forced categories** — candidates spanning functional / quality / constraint are
      flagged as such, not truncated to fit one box.
- [ ] **No context loss** — essential context (regulatory driver, safety rationale)
      survives classification; if it does not fit the table, it goes to Notes.
- [ ] **Consistent topics** — grouping uses one scheme (feature *or* topic), applied
      uniformly; no orphan groups of one item unless justified.
- [ ] **User story fit checked** — complex technical or regulatory candidates that the user
      story template cannot carry are extracted as declarative statements and flagged for
      detailed specification (*Reliance on User Story Template* pitfall).

## 4. Coverage, gap & dependency review `[AI4RE-adapted]`

- [ ] **Full-input coverage** — the input was re-read after extraction; every
      requirement-bearing statement is either in the table or consciously excluded (state
      why on request).
- [ ] **Gaps named** — missing requirement types (e.g., no quality requirements, no error
      handling), unanswered stakeholder questions and contradictions between statements are
      listed as open questions — never filled with invented content.
- [ ] **Interdependencies identified** — dependencies between candidates (prerequisite,
      conflict, shared constraint) are listed; "none found" is stated explicitly
      (*Missing Interdependencies* pitfall).
- [ ] **Patterns surfaced** — recurring pain points or needs across speakers/documents are
      summarized.

## 5. Anti-pitfall self-check before delivery `[AI4RE]`

One check per pitfall of the guide page:

- [ ] **Ambiguity and lack of detail** — vague input produced vague candidates → are they
      marked as needing clarification and validation instead of presented as final?
- [ ] **Misinterpretation** — nuanced domain-specific terms or stakeholder intentions
      involved → did I ask, mark `Assumption:`, or recommend SME review?
- [ ] **Over-categorization** — multi-category candidates flagged; no important context
      lost to the schema?
- [ ] **Missing interdependencies** — dependencies checked and reported (they are
      essential for planning and implementation)?
- [ ] **Lack of business context** — business goals known and used for relevance judgments,
      or their absence flagged as an open question?
- [ ] **Reliance on user story template** — complex technical/regulatory candidates routed
      to detailed specification instead of squeezed into user stories?
- [ ] Is the output labeled a set of **candidate requirements** — a draft requiring
      stakeholder validation and expert review?
