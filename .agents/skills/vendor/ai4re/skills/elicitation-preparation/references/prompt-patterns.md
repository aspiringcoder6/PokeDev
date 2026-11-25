# Prompt Patterns — Elicitation Preparation

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the templates and worked
> examples of the Explore cluster. Pattern names follow common prompt-engineering
> vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | Every template: "AI's role" (domain expert / interview expert / facilitation expert) + "My role" (requirements engineer) | Adopt the expert persona *and* model the requester's perspective; specialize the persona per use case (stakeholder analysis, interviewing, facilitation) |
| **Purpose priming** | "My purpose:" states the elicitation goal (foundational understanding; preparation for interviews and workshops; 3–7 agreed goals) | Keep the downstream elicitation activity in view — the artifact serves the *next* conversation with stakeholders, not itself |
| **Prompt chaining** (conversation staging) | Introduce a New Domain: Overview → System Context → Regulations → Actors → Glossary in one session; Identify Stakeholders: groups → individual mapping | Configure roles once, then issue focused follow-up prompts that build on prior answers; keep artifact names consistent across the chain |
| **Named-artifact constraint** | Fixed titles: "Introduction", "System Context", "Regulations and Standards", "Actors", "Glossary" | Fix the title and format before generating so artifacts drop into the workspace structure unchanged |
| **Framework anchoring** | Onion Model (Alexander, 2005) with its three named layers; MoSCoW/100-point in the workshop example | Classify against an explicit, cited framework instead of an ad-hoc taxonomy; the framework makes gaps visible (empty layer = missing stakeholders) |
| **Assumptions-listed-separately** | Stakeholder Groups: "If necessary, make assumptions and list them separately"; mapping: "state assumptions explicitly" | Separate assumption block after the deliverable; never merge guesses into the main table |
| **Artifact grounding** | "+ Add file with organizational chart"; "+ Add word file with goals" | Attach the authoritative artifact and restrict answers to it (only real roles/persons, only listed goals); consistency rule: names must match across artifacts |
| **Audience calibration** | Overview: "audience … some of whom may be unfamiliar with the domain", "avoiding unnecessary technical jargon while preserving essential accuracy" | State the reader explicitly; tune register to the least-informed legitimate reader without losing precision |
| **Target-quantity constraint** | Goal confirmation: "At the end I would like to have 3-7 main goals collected and agreed" | Give the AI a convergence target; forces prioritization and merging instead of open-ended lists |
| **Structured-interaction script** | Both interview templates produce timed, sectioned scripts; workshop template demands step-by-step conduct "with time allocations" | Ask for time-boxed sections — it converts knowledge into a runnable protocol |
| **Enumerated deliverable spec** | Plan Workshop task lists five required guide components | Enumerate required parts in the task; check each off in self-review (missing part = defect) |
| **Output format constraint** | `[FORMAT]` variable everywhere; "Confluence-ready Markdown table using pipe separators" with fixed columns | Fix format and columns before generating; deviations are defects |
| **Variable configuration** | All `[SQUARE_BRACKET]` variables ([DOMAIN], [SYSTEM], [NAME], [ORGANIZATION], [STAKEHOLDERS], [GOALS], …) | Resolve every variable before executing; unresolved variables are clarifying questions |
| **Recommendation closing** | Worked examples end with *Recommendation* / *Next Step Options* (engage experts early, validate Onion Model, RACI map) | End deliverables with prioritized next steps that hand over to the following elicitation activity |
| **Draft-not-decision** | Every page's conclusion: "expert validation ensures correctness and contextual relevance"; guides are "a starting point [to] be refined" | Label output as draft; require refinement by the requirements engineer and validation by domain experts |
| **Sensitive-data gate** | Identify Stakeholders pitfalls: org charts, recordings and internal documents must not go to public AI services without approval/anonymization | Check data sensitivity *before* processing or recommending upload; suggest anonymization (role IDs) as the default mitigation |
