# Prompt Patterns — Change Impact Analysis

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the template, worked example
> and pitfall mitigations of the Align cluster. Pattern names follow common
> prompt-engineering vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the use case uses it | How to apply |
|---------|----------------------------|--------------|
| **Role prompting with responsibility statement** | "AI's role: Specialist in impact analysis … Your responsibility is to analyze … and identify all affected requirements …" | State not just the persona but its concrete accountability; it scopes what "complete" means for the answer |
| **Context priming with user goal** | "Context: You support a requirements engineer who … plan and communicate necessary actions, prevent inconsistencies, and maintain up-to-date requirements" | Encode the downstream purpose so proposals are planning- and communication-ready, not just descriptive |
| **Stepwise task decomposition** | Task steps: screen → identify elements & affected requirements → map artifacts → propose actions → highlight risks → suggest missing artifacts | Execute the numbered steps in order; each step's output feeds the next |
| **Change decomposition before analysis** | Worked example opens with "Change request elements identified" (CR split into atomic changes) | Decompose the CR first; analyze impact per element so nothing is bundled or skipped |
| **Strict grounding with source typing** | "Name the source so that I can see what type of information you are referring to (for example: missing artifacts, given input, connected systems, or similar)" | Label every claim with its evidence class; separates extracted facts from inferences |
| **Exact-location referencing** | "show me the exact location where I should change the artefacts"; "use the exact file name or path" | Cite requirement IDs, section names, diagram node labels, method names — a locatable finding is an executable finding |
| **Output format constraint (table schema)** | Fixed six columns: Impacted Requirement / Artifact · Source · Type of Impact · Proposed Action · Dependencies / Risks · Comments | Fix the schema before generating; one row per impact, many rows per CR element |
| **Ownership assignment** | "name the responsible persons or departments (if known)"; worked example's "Suggested responsibilities" | Propose an owner per action stream; mark ownership guesses as suggestions |
| **Gap detection (negative-space prompting)** | "Also suggest missing artifacts" | Actively look for documents that *should* exist (rule catalogs, data dictionaries, test specs, interface notes) — absence is a finding |
| **Risk callouts + validation needs** | "Highlight risks, dependencies, or validation needs"; worked example ends with a pre-release validation checklist | End the deliverable with risks, dependency chains and what must be verified before rollout |
| **Category checklist sweep** | Pitfall mitigation: "Use a checklist for: UI, Service, Data Model, API, Integration, Reports" | Sweep every category per CR element so logical impacts are found behind textual ones |
| **Evidence enrichment on request** | Pitfall mitigations: provide traceability matrix, architecture diagrams, glossary, business rule doc, interface/service specs | When inputs are thin, ask for the specific artifact that closes the known blind spot instead of guessing |
| **Granularity normalization (post-processing)** | Pitfall mitigation: manually categorize output into fixed levels | After generating, re-group findings at consistent abstraction levels for estimation and clear ownership |
| **Draft-not-decision** | Pitfalls: developer/Legal/PO confirmation of AI findings | Label the analysis a draft; route rule changes to Legal/Compliance and technical findings to developers for confirmation |
