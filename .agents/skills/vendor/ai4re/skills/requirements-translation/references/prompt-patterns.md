# Prompt Patterns — Requirements Translation

> **Provenance:** `[AI4RE-adapted]` — patterns extracted from the templates, worked
> examples and pitfall sections of the Translate cluster. Pattern names follow common
> prompt-engineering vocabulary `[Supplementary]` where the guide uses none.

| Pattern | Where the cluster uses it | How to apply |
|---------|---------------------------|--------------|
| **Dual role prompting** | Every template: "AI's role" (MBSE expert, business analyst, UX designer, testing expert, software analyst) + "My role" (requirements engineer) | Adopt the use-case-specific expert persona *and* model the requester's perspective; switch personas per use case, not per conversation |
| **Purpose priming** | "My purpose:" line states the communication/quality goal before the task | Keep the end state (stakeholders can interpret and validate efficiently) in view, not just the mechanical conversion |
| **Interactive scoping** (ask-before-proceed) | Generate Model From Text: group requirements, then "Ask the user which group to start with" | Never translate a large artifact in one shot; propose scoped units with rationale and let the user pick the starting point |
| **Chunking / task splitting** | Model-from-text pitfalls ("break down large artifacts"); test-case pitfalls ("divide the given task into multiple sub tasks") | Split large specs, models or code bases into per-feature/per-module sub-tasks; deliver per chunk to avoid truncation |
| **Extract-then-transform** | Text From Model: "identify all possible relevant elements of the diagram in text" before generating requirements | Make the intermediate extraction (elements, actors, scenarios) an explicit output section — it is the traceability bridge between representations |
| **Named output sections** (format contract) | Model From Text: Grouping · Diagram elements · Model Representation · Validation Note; Source Code: Introduction · FR · NFR · Glossary · Traceability Note | Fix the section skeleton before generating; deviations are defects |
| **Validation note** | "Mention any assumptions made or gaps identified in the source text" (Model From Text, Text From Model); persona hypothesis labeling | End every translation with assumptions, gaps and interpretations — the reader must see where the source was silent |
| **Strict grounding** | Persona: "Only generate one persona, strictly based on the uploaded file"; test cases keep requirement IDs | Constrain generation to the provided artifact; label anything beyond it as hypothesis/assumption |
| **Fidelity constraint** (meaning lock) | Explain Requirements: "Maintain Accuracy: … does not change, add, or remove the core intent"; modal-verb pitfall | State the invariant explicitly in the prompt: intent, conditions and obligation levels are read-only |
| **Audience targeting** | `[STAKEHOLDER_GROUP]` variable; pitfall "what's 'simple' varies by audience" | Always name the target group; calibrate detail, focus and language to it; add audience-specific constraints (e.g. "executive language, no product-level details") |
| **Impact framing** | Explain Requirements: "What this means for you:" per item; "Why should they care about this?" | Pair every simplified item with its concrete benefit/impact for the audience — impact, not feature listing |
| **Negative-space prompting** | Explain pitfalls: "Do not list individual features…", "avoid fluff"; persona: "Avoid stereotypes and clichés" | Tell the model what *not* to produce; the cluster's pitfalls double as ready-made negative instructions |
| **Type-driven enumeration** | Test Cases: "including positive, negative, and edge cases where applicable"; sequence-diagram fragments (alt/opt/loop) | Enumerate along a closed type system (test types, fragment kinds) to force coverage instead of free association |
| **Traceability anchoring** | Test cases: "ID of the tested Requirement" column; source code: Traceability Note; model example maps elements to requirements | Carry source IDs/pointers into every output row or section; weak traceability (snippets, screenshots) is flagged, not hidden |
| **Self-correction loop** (error feedback) | Model-from-text pitfalls: "feed error messages back into the prompt", "validate syntax using automated tools" | Check generated model code against the renderer; on syntax error, feed the error back and regenerate until it parses |
| **Tool-importable output** | "ensuring it can be imported into modeling tools"; export offer (Excel) in the test-case example | Choose machine-consumable notations (PlantUML, Mermaid `[Supplementary]`, BPMN XML, CSV) so the artifact enters the toolchain without retyping |
| **Context injection** | Model-from-text recommendations: RAG, domain documents, tailored system prompts | When domain context is thin, request or attach relevant documents rather than letting the model guess |
| **Draft-not-decision** | Every page's conclusion: expert review required; results are "conversation starters" | Label output as draft; recommend the matching expert (domain, UX, test, architecture) for validation |
