# Prompt Patterns — Requirements Traceability

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the templates and worked
> examples of the Assign cluster. Pattern names follow common prompt-engineering vocabulary
> `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Role prompting** | Tag: "AI assistant who classifies software requirements into exactly one category"; Trace: "Requirements engineer" | Adopt the stated role; it fixes the decision perspective (classifier vs. artifact mapper) |
| **Context priming** | "Context:" line names the goal state — "consistent, explainable, and reproducible classification"; "mapping requirements … to enable traceability" | Keep the management goal (auditability, ownership, coverage) in view, not just the mechanical task |
| **Rule-based decision procedure** | Tag decision rules: match via include criteria → single match → primary goal tie-break → UNCLEAR | Encode explicit, ordered if/else rules; apply them verbatim so reruns are reproducible |
| **Single-label constraint** | Tag: "exactly one category" | Force one primary label per item; ambiguity goes to the escape category, never to multi-labeling |
| **Escape category (UNCLEAR)** | Tag decision rule 4 | Provide a defined out for undeterminable cases; require an explanation of the ambiguity and the missing information |
| **Explainable reasoning** (cite-your-rule) | Tag reasoning rules: cite the triggering include criterion | Every decision names the rule that produced it — classifications become reviewable one by one |
| **Secondary-match disclosure** | Tag reasoning rules: state the secondary matching category | Do not hide near-misses; disclosing them exposes taxonomy overlaps and makes tie-breaks auditable |
| **Strict evidence grounding** | Trace: "Base your answer strictly on the actual content of the artefacts, not on file names" | Metadata (file names, titles alone) never counts as evidence; only content does |
| **Exact-location citation** | Trace: "Specify the exact location (page, section, slide, or paragraph) and provide a direct quote or summary" | Every link carries a pointer a human can check in seconds; unverifiable links are defects |
| **Explicit-absence reporting** | Trace: "If the requirement is not found or only partially addressed, state this explicitly" | Report negative results deliberately — silence is indistinguishable from an unchecked artifact |
| **Link typing (pre/post)** | Trace: classify references as "pre" (source) / "post" (downstream) | Type every link; typed links enable direction-specific coverage checks and impact analysis |
| **Synonym expansion** | Trace pitfalls: literal matching causes false negatives → explicitly search for synonyms | Expand key terms with synonyms before concluding "not found"; reuse an existing synonym table |
| **Bias awareness** | Trace pitfalls: selection bias; Tag pitfalls: hidden bias in training data | Name what the input set or a generic taxonomy likely underrepresents instead of silently echoing it |
| **Abstraction restraint** | Trace pitfalls: AI rationale — plausible abstractions beyond the evidence | Stay at the evidence level; downgrade "reading between the lines" to `Assumption:` or drop it |
| **Gap analysis + recommendation** | Trace worked example: "Not Found", "Gaps / Issues Identified", "Recommendation" | End tracing deliverables with concrete next steps (record links, variance log, DoD, UAT plan) |
| **Output format constraint** | Tag: `[OUTPUT FORMAT]` (Excel · CSV · markdown table) | Fix the format before generating; deviations are defects |
| **Draft-not-decision** | Cluster conclusions: "human judgement ensures alignment", "expert validation ensures accuracy" | Label output as draft; require human expert validation |
