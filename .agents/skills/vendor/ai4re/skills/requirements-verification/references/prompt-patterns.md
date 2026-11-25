# Prompt Patterns — Requirements Verification

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the templates and worked
> examples of the Verify cluster. Pattern names follow common prompt-engineering
> vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | Every template: "AI's role" (RE analyst / MBSE-UML expert / code-analysis expert) + "My role" (requirements engineer) | Adopt the expert persona *and* model the requester's perspective; pick the persona per use case |
| **Pairwise exhaustive comparison** | Analyze Requirements Consistency: "Compare all requirements pairwise … Include each pair once" | Enumerate pairs systematically instead of scanning impressionistically; disclose skipped ranges |
| **Taxonomy-constrained classification** | Detection scope with 10+ categories and named subtypes | Classify against a fixed taxonomy; allow an "other" bucket only with explicit naming and justification |
| **Single-categorization rule** | "Do not repeat the same pair in multiple sections; choose the most appropriate category" | One finding, one home — prevents inflated finding counts and double-counted issues |
| **Strict evidence grounding** | "Do not alter requirement text; quote it exactly"; "Only report findings that cite exact element names from the input" | A finding without a verbatim quote, exact element name or code reference does not exist; delete it |
| **Hidden chain of thought** | "Execution steps (do not include in the output)" — parse, ID, compare, classify, render | Prescribe the reasoning procedure but keep the deliverable clean; process transparency lives in the prompt, not the report |
| **Deterministic ID assignment** | "Preserve existing IDs; generate REQ-### IDs for missing ones in reading order" | Make findings addressable and re-runs comparable by stable, rule-based identifiers |
| **Null-result handling** | "If no related pairs are found, output a single section noting that no issues were detected" | Define the empty case up front so absence of findings is a verifiable result, not silence |
| **Verdict scale constraint** | Spec-vs-code: Match / Partial / Missing / Extra | Fix the verdict vocabulary before comparing; "Extra" forces attention to unspecified behavior, not just gaps |
| **Metamodel-guided parsing** | Check Model Consistency: "Identify all model elements according to the UML metamodel" | Extract elements class by class (classes, operations, associations, states, actors) before comparing — structure first, judgment second |
| **Finding–Impact–Suggestion triad** | Model consistency worked example | Report each finding with its consequence and a concrete fix; suggestions branch on intent ("if same concept … / if different concept …") |
| **Attribute augmentation** | Multi-document tip: add "Level of Abstraction", document name, or "Traced to: Sys-Req-1" attributes | Feed hierarchy metadata into the prompt so legitimate cross-level similarity is not misclassified as duplication |
| **Iterative convergence** | "re-run the checks until the documentation achieves consistency"; new chat session per model-comparison iteration | Treat one run as one sample: repeat on large inputs until re-runs surface nothing new; reset context between iterations |
| **Scope caveat framing** | Spec-vs-code pitfalls: context gaps, unverifiable NFRs; model pitfalls: consistency ≠ correctness | End reports with what could *not* be checked; never let a clean table imply full verification |
| **Draft-not-decision** | All pitfall sections: human oversight remains necessary | Label output as a draft; require expert review of both flagged and unflagged content |
