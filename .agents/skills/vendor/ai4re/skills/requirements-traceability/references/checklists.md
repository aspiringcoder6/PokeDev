# Checklists — Requirements Traceability

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* sections
> of the Assign cluster). Quality-criteria operationalizations are
> `[Supplementary: ISO/IEC/IEEE 29148:2018, IREB CPRE Glossary, Gotel & Finkelstein 1994]`.

## 1. Taxonomy pre-flight check (before tagging) `[AI4RE]`

Run before classifying a single requirement; every "no" goes back to the user.

- [ ] **Sharp definitions** — each category has a purpose and explicit include criteria;
      otherwise the AI classifies by linguistic similarity instead of semantic meaning.
- [ ] **No unresolved overlaps** — no two categories partially describe similar concepts
      (e.g. collaboration vs. permissions) without a tie-breaking rule; ambiguous taxonomies
      create long-term structural confusion.
- [ ] **Complete category records** — every category has ID, name, purpose description and
      criteria description.
- [ ] **Escape hatch defined** — `UNCLEAR` (or equivalent) exists so ambiguity is surfaced,
      never forced into a wrong category.
- [ ] **Domain fit checked** — taxonomy reflects the user's business domain, not generic
      patterns; legacy assumptions and organizational biases in a proposed taxonomy are
      named, not reproduced.

## 2. Classification review (after tagging) `[AI4RE]`

- [ ] **Exactly one category per requirement** (or `UNCLEAR`) — single-category mapping
      supports clear ownership.
- [ ] **Criterion cited** — every classification names the include criterion that triggered
      the primary category.
- [ ] **Secondary matches disclosed** — where multiple categories matched, the secondary
      category is stated and the primary-goal decision is visible.
- [ ] **UNCLEAR explained** — why the intent is ambiguous + what information is missing.
- [ ] **No FR/NFR confusion** — functional requirements containing words like "quick",
      "efficient", "intuitive" are not mislabeled as non-functional; classify by intent,
      not surface vocabulary.
- [ ] **NFR taxonomy** — NFRs classified by ISO/IEC 25010:2023 (+ *Randbedingungen*)
      unless the user defined another taxonomy; product accessibility vs. accessibility
      proof obligations kept apart (Q04 vs. Q10).
- [ ] **Formulation-independence spot check** — pick pairs of requirements that mean the
      same but are worded differently; they must share a category.
- [ ] **Reproducibility** — decision rules applied verbatim; a rerun with the same rules
      would yield the same result (critical for auditable decisions, e.g. compliance).
- [ ] **No unexamined trust** — output that merely *looks* well-structured was spot-checked
      against the raw requirements before delivery (2–3 samples minimum).

## 3. Trace-link review (after tracing) `[AI4RE]`

- [ ] **Content-grounded** — every link based on artifact content, never on file names.
- [ ] **Evidence complete** — document title/author (from the first page, if available and
      meaningful), exact location (page, section, slide, paragraph, timestamp) and a direct
      quote or summary per link.
- [ ] **Pre/post classified** — every link labeled "pre" (source) or "post" (downstream);
      indirectly related artifacts marked as such, not forced into a direct link.
- [ ] **Absence stated explicitly** — requirements not found or only partially addressed
      are reported as such; missing artifact classes (code, tests, validation results)
      listed under "Not Found".
- [ ] **Synonym-aware** — key terms searched including synonyms before concluding "not
      found"; false negatives from literal matching are a named pitfall.
- [ ] **No over-abstraction** — no high-level generalizations beyond what the evidence
      explicitly states; plausible-but-unsupported links removed or marked `Assumption:`.
- [ ] **Evidence verified in context** — quoted snippets checked against their surrounding
      text; do not overtrust the small evidence portions the AI presents.
- [ ] **Selection bias flagged** — if the artifact set favors certain contexts, terms or
      regions, the report says so and names what is likely underrepresented.

## 4. Traceability completeness gate `[Supplementary: ISO/IEC/IEEE 29148:2018]`

- [ ] **Bidirectional** — both directions addressed: source(s) identified (or absence
      stated) *and* downstream coverage assessed (or absence stated).
- [ ] **Acceptance-criteria coverage** — if the requirement has acceptance criteria, each
      one is mapped to covering evidence or listed as a gap.
- [ ] **Gap list + recommendation** — the report ends with identified gaps and concrete
      next steps (links to record in the RM tool, tests to create, Definition-of-Done
      additions, validation to plan).
- [ ] **Link granularity fits purpose** — links point to the smallest useful unit
      (paragraph/slide/test case), not just to whole documents.

## 5. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] Taxonomy or requirement intent was ambiguous → did I ask, or mark assumptions?
- [ ] Did I reproduce a generic/legacy classification pattern that may not suit this
      domain? (Hidden bias in training data.)
- [ ] Would a rerun produce the same tags and links? If not, which rule is underspecified?
- [ ] Is the output labeled a **draft** requiring human expert validation?
- [ ] Sensitive artifacts involved → did I remind the user about confidential data and
      external AI services?
