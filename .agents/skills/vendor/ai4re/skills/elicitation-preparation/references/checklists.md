# Checklists — Elicitation Preparation

> **Provenance:** Pitfall-derived checks are `[AI4RE]` (from the *Pitfalls & Tips* sections
> of the Explore cluster). Operationalized quality criteria are
> `[Supplementary: IREB CPRE, interviewing and facilitation practice]`.

## 1. Domain briefing gate `[AI4RE-adapted]` (from Introduce a New Domain pitfalls)

Check every domain-introduction artifact; every "no" must be fixed or logged as an open
question.

- [ ] **Completeness disclaimer present** — AI knowledge may miss critical domain-specific
      details, regulatory requirements or recent developments; the briefing says so and
      recommends expert validation.
- [ ] **Regulations verified by a professional** — the Regulations and Standards list
      carries an explicit note that a qualified professional must ensure complete technical
      compliance; region/jurisdiction stated or asked for.
- [ ] **Terminology used correctly** — domain terms, acronyms and their relationships are
      not oversimplified; ambiguous acronyms defined on first use (contextual
      misinterpretation is a named pitfall).
- [ ] **Audience-appropriate** — accessible tone, no unnecessary jargon, yet essential
      accuracy preserved (both demanded by the template).
- [ ] **All five artifacts consistent** — actors in *Actors* match stakeholders named in
      *Introduction*; terms in *Glossary* match usage in all other artifacts; systems in
      *System Context* reappear where relevant.
- [ ] **Recency flagged** — fast-moving items (new regulations, evolving standards) marked
      as "verify current status".

## 2. Stakeholder landscape gate `[AI4RE-adapted]` (from Identify Stakeholders template & pitfalls)

- [ ] **All Onion layers populated** — System, Immediate *and* Wider; an empty Wider layer
      (regulators, vendors, schemes, indirect users) signals incompleteness.
- [ ] **Sorted by influence/importance** — priority (High/Medium/Low) assigned to every
      group with a defensible rationale.
- [ ] **Assumptions listed separately** — scope, regulatory context and architecture
      assumptions in their own block, not buried in the table.
- [ ] **Non-obvious groups considered** — compliance, risk, operations, data
      protection/GDPR, audit, training, business continuity, external partners.
- [ ] **Mapping grounded** — every mapped individual/role exists in the provided org chart;
      external stakeholders mapped to internal owners; group names identical to the
      stakeholder list; ambiguous mappings carry `Assumption:`.
- [ ] **Sensitive data handled** — org chart upload to external services questioned;
      anonymization (role IDs, generic role names) or DPO/security approval recommended.
      `[AI4RE]`
- [ ] **Next step named** — validate classification with business and IT; engage
      high-priority groups first.

## 3. Interview guide gate `[AI4RE]` (from Prepare Interview pitfalls)

- [ ] **Not generic** — questions reference the concrete system, domain artifacts (e.g.
      NOTAMs, ledgers, work orders) and the stakeholder group's actual work; a guide that
      fits any system fails.
- [ ] **Domain-specific detail present** — terminology, regulatory requirements and
      specialized workflows of the domain appear in the questions.
- [ ] **Stakeholder-aligned** — questions distinguish this stakeholder's perspective from
      others'; no one-size-fits-all guide across groups.
- [ ] **Context-aware** — organizational structures, dependencies and (where known)
      politics reflected; ask the user if unknown.
- [ ] **Not overloaded** — few questions per section; the interviewer keeps flexibility;
      total fits the stated time budget.
- [ ] **No leading questions** — no phrasing that suggests a preferred answer ("Wouldn't it
      be better if…").
- [ ] **No redundancy** — no two questions ask the same idea in different words.
- [ ] **Clear terminology** — vocabulary matches the stakeholder's, neither too technical
      nor too abstract.
- [ ] **Prioritized** — critical topics for this role and project phase come first; not all
      topics treated as equally important.
- [ ] **Open-ended by default** `[Supplementary: interviewing practice]` — exploratory
      questions start with what/how/describe/walk me through; closed questions only for
      confirmation (goal-confirmation type).
- [ ] **Goal confirmation converges** — script drives toward 3–7 agreed main goals, with
      per-goal validity/completeness/wording checks and a final agreement step.

## 4. Workshop plan gate `[AI4RE]` (from Plan Workshop pitfalls)

- [ ] **Real-world, not idealized** — plan works under stated constraints (limited time,
      partial availability, competing priorities), not textbook conditions.
- [ ] **Techniques fit the domain** — no method mismatch (e.g. free-form story mapping in a
      regulatory-driven context without adaptation).
- [ ] **Stakeholder dynamics addressed** — power imbalances, interpersonal dynamics and
      political sensitivities acknowledged; facilitation tips cover them.
- [ ] **Technical constraints respected** — legacy systems, architecture decisions and data
      privacy limits reflected in what the workshop can explore.
- [ ] **Facilitator skill level matched** — techniques match the user's stated experience;
      simpler alternatives offered where advanced methods assume skill.
- [ ] **Adaptivity built in** — plan allows reacting to group energy, resistance and
      emerging topics; not a rigid method sequence.
- [ ] **Follow-up is substantial** — post-workshop synthesis, participant validation
      (summary within days), repository update and traceability are planned as real effort,
      not a footnote.
- [ ] **All five template parts present** — planning, technique adaptation, step-by-step
      conduct with timings, facilitation tips, documentation/validation advice.

## 5. Anti-pitfall self-check before delivery `[AI4RE]`

- [ ] Input was ambiguous → did I ask, or mark assumptions separately (as the stakeholder
      template demands)?
- [ ] Personal or confidential data involved (org chart, goals document, recording) → did I
      raise the approval/anonymization caution? (Teams recordings cannot be fed to external
      chatbots directly — transcribe first, if policy allows.)
- [ ] Domain knowledge vs. provided artifacts clearly separated; nothing invented (people,
      org units, regulations presented as certain)?
- [ ] Is the output labeled a **draft / starting point** the requirements engineer must
      refine — with expert validation for correctness and contextual relevance?
- [ ] Are open questions and risks listed at the end of the deliverable?
