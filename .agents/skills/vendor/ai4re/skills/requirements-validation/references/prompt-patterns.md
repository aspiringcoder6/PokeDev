# Prompt Patterns — Requirements Validation

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the template, rules and
> pitfalls of the Validate cluster (*Generate Wireframe*). Pattern names follow common
> prompt-engineering vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | "AI's role" (RE expert with UI/UX expertise) + "My role" (requirements engineer) | Adopt the expert persona *and* model the requester's perspective; the artifact must serve a third party — the target group |
| **Purpose priming** | "My purpose: Validation of requirements with stakeholders with the help of wireframes" | Keep the end state in view: the wireframe is a validation aid, not a design deliverable |
| **Strict grounding / sole source of truth** | "Input (choose ONE) as primary and sole source of truth" | Force a single authoritative input; everything in the output must derive from it |
| **Negative constraints** | Derivation rule ("do not add anything not explicitly supported") and navigation rule ("no invented dashboards/menus/quicklinks") | State what the model must *not* do — countering its tendency to close gaps helpfully but silently |
| **Channel separation** | Design context accepted "as visual direction only" | Give secondary inputs an explicit, limited role so style material cannot smuggle in structure |
| **Rule modularity** | "delete the optional ones ID3 to 6 if not needed" | Encode behavior as numbered, individually removable rules; confirm the active set before generating |
| **State-space enumeration** | States rule: empty, loading, error per top-level screen | Enumerate required variants explicitly so completeness is checkable, not hoped for |
| **Inline traceability marking** | Traceability rule: small red tag "Ref: US-1" next to each derived element | Make provenance visible *inside* the artifact so review findings map back to requirements |
| **Bounded assumption budget** | Assumptions rule: minimal assumptions, listed, max. 5 | Cap assumptions; exceeding the cap signals the input is too thin — ask instead |
| **Ambiguity surfacing with alternatives** | Ambiguity rule: highlight and propose two alternative interpretations | Never resolve contradictions unilaterally; present options for the stakeholder to decide |
| **Visual annotation convention** | Light yellow background for states/assumptions/ambiguities; red tags for traceability | Fix an annotation vocabulary up front so reviewers can distinguish derived, assumed and uncertain content at a glance |
| **Output format constraint** | "One self-contained HTML file (embedded CSS, no external libraries), clearly separated sections per screen" | Fix the format before generating; self-containment makes the artifact portable to any review setting |
| **Variable configuration** | `[SYSTEM]`, `[DOMAIN]`, `[TARGET GROUP]`, `[APPLICATION TYPE]`, `[LANGUAGE]`, `[STYLE]` | Resolve every variable before executing; unresolved variables are clarifying questions |
| **Draft-not-decision** | Pitfalls: comprehensive-looking wireframes create "a misleading sense of confidence" | Label the output a draft validation aid requiring expert and stakeholder review |
