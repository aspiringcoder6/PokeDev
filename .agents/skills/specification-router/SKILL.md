---
name: specification-router
description: >-
  Assess software requirements for clarity and completeness and select the appropriate
  specification workflow. Use Spec Kit for independently scoped new systems, modules,
  or capabilities; use OpenSpec for changes, additions, fixes, or extensions to existing
  capabilities. Use when reviewing requirements from tickets, messages, documents, or
  existing specs, before technical planning or implementation.
compatibility: Requires access to the relevant project context and the selected framework's installed agent skills and CLI. Interactive workflows require a human-question channel.
metadata:
  version: "0.1.0"
---

# Specification Router

## Purpose

Route each requirement to the appropriate native specification workflow. Reuse the installed Spec Kit or OpenSpec instructions, templates, and validators; do not recreate a parallel specification framework. Stop at requirement assessment or specification readiness, as requested. This skill does not authorize implementation, deployment, or approval.

## 1. Establish the scope

Read the normalized requirement, linked evidence, project rules, relevant existing specifications, and affected code or interfaces. Use available read-only search and retrieval tools to fill gaps. Identify the intended behavior, target project, existing capability (if any), and whether an active specification/change already owns the request.

Distinguish confirmed requirements, observed current behavior, assumptions, and unresolved decisions. Absence of a document or a search result does not prove that a capability is new. If missing access or conflicting evidence prevents classification, return `needs_context` with the evidence needed. Do not invent a baseline.

## 2. Choose exactly one workflow per scope

Apply this project routing policy, not a claim about the limitations of either framework:

| Route | Selection rule |
| --- | --- |
| `spec-kit` | A new system, module, or independently scoped capability whose requirements must be defined as a coherent whole. It may depend on existing services without being an extension of their behavior. |
| `openspec` | A modification, addition, removal, bug fix, compatibility change, or refactor within an existing capability, contract, or workflow. A new endpoint or class alone does not constitute a new capability. |

- Preserve an existing active Spec Kit feature or OpenSpec change for the same scope; do not create competing artifacts. Report any exception to the default policy. Honor explicit project or user framework selection where permitted.
- For mixed work, split only independently specifiable scopes with clear contracts. Record their dependencies and route each separately. If a new element is inseparable from a change to an existing capability, use OpenSpec for the coherent change. If the classification would materially alter scope and cannot be established from evidence, return a clarification finding.
- Explain the selection with evidence about existing capabilities and the intended change, not keywords or ticket labels.

## 3. Delegate to the selected native skills

Resolve the installed skill by name through the host's skill mechanism (for Codex, typically `.agents/skills/<name>/SKILL.md`). Invoke it with the requirement, relevant evidence, project constraints, and desired output boundary. If native invocation is unavailable but the installed instructions are readable, follow those instructions directly, including their scripts, templates and prerequisites. Skill names are not shell commands.

Use the installed version as the authority for paths, hooks, CLI options and artifact ordering. Never claim a skill ran unless it was executed. If the required framework is missing or its prerequisites fail, return `blocked` with the missing dependency; do not silently substitute the other framework or initialize/upgrade tooling without authorization.

### Route A — Spec Kit

1. Load project governance and locate the active feature if one exists. Check prerequisites using the native workflow. Do not recreate a constitution or feature directory when one already exists.
2. For a new spec, use `speckit-specify` to produce the feature specification and built-in requirements quality checklist. For an existing spec, reuse it. Pass only evidenced requirements and explicitly identified assumptions; do not present inferred business decisions as confirmed.
3. Use `speckit-clarify` to examine gaps and material ambiguities in the active feature specification. Resolve factual questions through available evidence first; route unresolved decisions to the human-question channel. Record confirmed answers through the native workflow.
4. Use the built-in requirements checklist maintained by the specify/clarify workflow. Invoke `speckit-checklist` only when a targeted domain checklist is needed (e.g., permissions, UX, integration). Assess each relevant criterion against the spec and evidence; checklist generation is not itself a pass. Respect reviewer ownership of custom checklist completion.
5. Reassess after clarification. Return the native spec and checklist locations, remaining issues and readiness verdict. Do not invoke `speckit-plan`, `speckit-tasks`, or implementation from this skill.

### Route B — OpenSpec

1. Resolve the project's OpenSpec root/store and current active changes using its installed CLI and instructions. Read relevant main capability specs, active change artifacts, project context and code. Preserve the selected store and exact capability paths across calls.
2. Use `openspec-explore` for investigation and clarification: identify current behavior, intended delta, impacted contracts, compatibility constraints, and unchanged behavior. Use evidence to separate a bug from a new requirement; never assume current code is the intended contract. Exploration does not implement code or automatically create artifacts.
3. If only assessment is requested, stop after the exploration and readiness review. When artifact authoring is authorized and material questions are resolved, use the native artifact workflow:
   - Prefer the installed granular workflow or Explore's authorized capture mechanism for proposal and delta-spec artifacts when only specification is requested. Follow the configured schema dependencies and CLI-provided artifact instructions. Do not manually scaffold a change folder or bypass a required dependency. Request authorization for any unrequested prerequisite artifact when required by the native workflow.
   - Use `openspec-propose` when the caller authorizes the full proposal (including design and tasks under the default schema). Do not use it just to evaluate requirement clarity.
   - Reuse an existing change rather than generating a duplicate. Preserve existing capability paths and express changes using the native delta format; do not overwrite the main specs. For behavior-preserving work, follow the installed schema's explicit no-spec-delta mechanism if applicable.
4. Run the applicable native validation for authored artifacts (e.g., `openspec validate <change> --strict`, using the selected store and supported flags). If a deliberately partial change cannot be fully validated yet, report validation as pending, not passed. Structural validation is not proof of semantic correctness.
5. Return the native change/artifact locations, remaining issues and readiness verdict. Do not apply, sync, archive, or implement the change.

## 4. Assess readiness and hand off clarification

Reuse the selected workflow's assessment rather than running another redundant review. For both routes, ensure its findings cover the relevant goal and scope, actors and behavior, business rules and exceptions, measurable acceptance criteria, dependencies, compatibility and material non-functional constraints. For OpenSpec, explicitly cover the before/after difference and behavior that must remain unchanged. For bugs, establish expected vs observed behavior and a reproducible or otherwise verifiable failure. Mark non-applicable dimensions as such; do not invent requirements merely to complete a checklist.

For each substantive gap, contradiction or ambiguity, identify the affected requirement, evidence, impact and resolution. Search permitted sources before asking humans. Escalate only decisions that cannot be established from available authoritative evidence or fall outside delegated authority. Provide a focused question and, when useful, alternatives and a suggested owner role. Do not select an unverified individual or send questions directly from this skill.

Interactive native workflows may ask questions or request write confirmation. In an automated harness, route those prompts to the existing human-interaction service, persist the continuation state and resume with actual answers. If the host cannot relay or resume native interaction, stop with the findings and required next action. Do not simulate answers, bypass native confirmation, or treat an input ticket as blanket authorization for artifact writes or hooks.

## 5. Return a common handoff

Return a concise assessment; keep native artifacts as the source of truth rather than generating a duplicate specification. Use the following machine-readable shape when called by an orchestrator (omit inapplicable optional fields; use empty arrays when there are no findings):

```yaml
route: spec-kit | openspec | unresolved
status: ready_for_spec | spec_ready | needs_context | needs_clarification | awaiting_authorization | blocked
route_reason: <classification and evidence>
evidence: [<source references>]
native_steps: [<skill name and outcome: executed, pending, or failed>]
artifacts: [<actual native artifact paths>]
findings:
  - requirement: <id or relevant statement>
    issue: <specific gap or conflict>
    blocking: true
    evidence: [<references or missing evidence>]
    resolution: retrieve_context | human_decision | agent_update
    question: <if human decision is needed>
    suggested_role: <if known>
next_action: <concrete continuation>
```

- `ready_for_spec`: assessment only; enough information to author a spec, not an assertion that a spec exists.
- `spec_ready`: authorized native specification exists, applicable quality checks have passed, and no blocking findings remain. This is not approval to implement.
- `needs_context` / `needs_clarification`: information or decisions remain; do not mark ready. `awaiting_authorization` is for required approvals/confirmation; `blocked` is for missing or failed prerequisites that prevent progress.
- Reuse prior findings, answers and native artifacts on subsequent runs. Reopen only findings affected by new information. Preserve source references and note any unverified assumptions. Do not mark a requirement ready merely because a framework command succeeded.

## Routing examples

| Requirement in context | Expected route |
| --- | --- |
| Build an independent billing module where billing does not exist | Spec Kit |
| Add MoMo as a payment method to an existing payment workflow | OpenSpec |
| Add a new endpoint to an existing order management capability | OpenSpec |
| Fix an existing refund calculation that violates its documented rule | OpenSpec |
| Build a new independent reporting capability in an existing application | Spec Kit |
| Add a new integration inseparable from changes to existing authentication | OpenSpec |
| “Improve reporting” with no accessible baseline or project context | Unresolved; retrieve context or clarify |

## Upstream references

- [Spec Kit: specify](https://github.com/github/spec-kit/blob/main/templates/commands/specify.md), [clarify](https://github.com/github/spec-kit/blob/main/templates/commands/clarify.md), [checklist](https://github.com/github/spec-kit/blob/main/templates/commands/checklist.md)
- [Spec Kit: Codex integration](https://github.com/github/spec-kit/blob/main/docs/integrations/codex.md)
- [OpenSpec: explore](https://github.com/Fission-AI/OpenSpec/blob/main/skills/openspec-explore/SKILL.md), [propose](https://github.com/Fission-AI/OpenSpec/blob/main/skills/openspec-propose/SKILL.md), [CLI](https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md)
- [Agent Skills format](https://agentskills.io/specification)
