# Checklists — AI4RE Master Consultant

> **Provenance:** `[AI4RE-adapted]` — consolidates the general cautions and pitfall themes
> of the AI4RE Prompt Guide at orchestration level; operationalization is
> `[Supplementary: this repository]`.

## 1. Intake checklist (before planning)

- [ ] RE task(s) classified against the routing table; classification stated to the user.
- [ ] Domain, system under consideration, target audience and quality standard known or
      asked for.
- [ ] Input artifacts identified (transcript? spec? model? code? nothing yet?).
- [ ] Sensitive-data reminder given if the user is about to paste confidential material
      destined for external AI services. `[AI4RE]`
- [ ] Out-of-scope parts (not RE, or not covered by AI4RE) named as such.

## 2. Plan checklist (before executing)

- [ ] Every step maps to exactly one skill; preconditions satisfied by upstream steps.
- [ ] Clarifying questions of all steps collected and asked once, centrally.
- [ ] Expected artifact per step named.
- [ ] Verification pass scheduled after steps that change requirements.

## 3. Cross-skill review (after the last step)

- [ ] **Terminology** — all artifacts use the primary terms of the synonym table/glossary;
      no step reintroduced banned variants.
- [ ] **Consistency** — no contradictions between artifacts of different steps (persona vs.
      stakeholder table, test case vs. acceptance criterion, model vs. text).
- [ ] **Abstraction levels** — goals, requirements and design details not mixed within one
      artifact.
- [ ] **Traceability thread** — every final artifact traces back to its source (transcript
      line, stakeholder, parent requirement); no orphans introduced between steps.
- [ ] **Assumptions & open questions** — consolidated, deduplicated, none silently dropped;
      answered questions removed with their answer noted.
- [ ] **Per-step self-reviews** — each executed skill ran its own self-review protocol; no
      step skipped it for speed.
- [ ] **Draft label** — final deliverable states that expert validation is required. `[AI4RE]`

## 4. Anti-pitfall supervision `[AI4RE-adapted]`

- [ ] No step invented domain facts, benchmarks or stakeholders (plausibility ≠ truth).
- [ ] Ambiguity was escalated as questions, never silently resolved.
- [ ] AI output treated as draft throughout — no step's output was presented as decided.
- [ ] Human review points recommended where domain/regulatory nuance is involved.
