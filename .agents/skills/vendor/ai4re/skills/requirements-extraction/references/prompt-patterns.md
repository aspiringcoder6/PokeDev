# Prompt Patterns — Requirements Extraction

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the template and worked
> example of the Extract cluster. Pattern names follow common prompt-engineering
> vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | Template: "AI's role" (expert in requirements engineering) + "My role" (requirements engineer) | Adopt the expert persona *and* model the requester's perspective; add domain expertise when nuanced terminology is involved |
| **Purpose priming** | "Purpose:" line states the goal (identify the *relevant* requirements) before the task | Keep relevance in view — extraction is filtering for what matters, not transcribing everything |
| **Output format constraint** | Two-column table spec with per-column instructions | Fix format before generating; deviations are defects |
| **Evidence quoting** (strict grounding) | Column 2 'Reference': "Quote the input for this requirement" | Every candidate carries a verbatim source quote; no quote → no candidate. Separates *extracted* from *suggested* |
| **Template-guided reformulation** | Column 1: "ideally using the user story template: As a [role], I want [feature], so that [benefit]" | Use the template as default, not dogma — the guide's pitfall warns it may not suffice for complex technical or regulatory requirements |
| **Whole-context-first reading** | Worked example: table derived from the full interview, duplicates merged, multiple quotes per candidate | Read the entire input before extracting; grouping, merging and relevance need the whole picture |
| **Classification with escape hatch** | RE task description: functional / quality / constraint; pitfall *Over-Categorization* | Classify, but flag multi-category candidates instead of forcing them — context loss is worse than a fuzzy label |
| **Gap surfacing** | Cluster page: "recognizing patterns, and closing gaps"; pitfalls on missing interdependencies | Report what the input does *not* cover as open questions; never fill gaps with invented content |
| **Recommendation closing** | Worked example ends with: validate with stakeholders (MoSCoW), refine with acceptance criteria/KPIs, check context | End deliverables with validation, prioritization and refinement next steps, plus offered follow-ups |
| **Variable configuration** | AI4RE anatomy; appended stakeholder input | Resolve every variable before executing; unresolved variables are clarifying questions |
| **Draft-not-decision** | Conclusion: "expert review ensures correctness and contextual alignment" | Label output as candidate requirements — a draft requiring stakeholder validation |
