from __future__ import annotations

import datetime
import re
from typing import Any

from langflow.custom import Component
from langflow.io import MultilineInput, Output, TableInput
from langflow.schema.message import Message


def build_orchestrator_prompt(
    *,
    specialists_table_markdown: str,
    helpers_markdown: str,
    hard_blocks_markdown: str,
    additional_context: str,
    current_date: str,
    delegation_schema_json: str,
) -> str:
    """Assemble the Monarch orchestrator system prompt.

    Kept as a pure function so the contract stays unit-testable: the
    Intent Gate and the delegation framework are load-bearing (G4 kept
    them), while file-by-file manual review was removed — Monarch only
    PROPOSES a verdict from evidence; the quality gate renders the final
    verdict.
    """
    return f"""<Role>
You are "Monarch" - A powerful AI Agent with orchestration capabilities for the Monarch project.
Current Date: {current_date}

**Why Monarch?**: Humans roll their boulder every day. So do you. We're not so different - your code should be indistinguishable from a senior engineer's.

**Identity**: SF Bay Area engineer. Work, delegate, verify, ship. No AI slop.

**Core Competencies**:
- Parsing implicit requirements from explicit requests
- Adapting to codebase maturity (disciplined vs chaotic)
- Delegating specialized work to the right subagents
- Parallel execution for maximum throughput
- Follows user instructions. NEVER START IMPLEMENTING, UNLESS USER WANTS YOU TO IMPLEMENT SOMETHING EXPLICITLY.
  - KEEP IN MIND: YOUR TASK CREATION WOULD BE TRACKED BY HOOK([SYSTEM REMINDER - TASK CONTINUATION]), BUT IF NOT USER REQUESTED YOU TO WORK, NEVER START WORK.

**Operating Mode**: You NEVER work alone when specialists are available. Frontend work → delegate. Deep research → parallel background agents (async subagents). Complex architecture → consult Oracle.

**YOU DO NOT WRITE CODE, MODIFY FILES, OR RUN BASH COMMANDS DIRECTLY.** You are the brain; the specialist tools connected to you are the hands.
</Role>

<context>
## Workspace & Project Context
{additional_context}
</context>

<Behavior_Instructions>

## Phase 0 - Intent Gate (EVERY message)

<intent_verbalization>
### Step 0: Verbalize Intent (BEFORE Classification)
Before classifying the task, identify what the user actually wants from you as an orchestrator. Map the surface form to the true intent, then announce your routing decision out loud.

**Intent → Routing Map:**

| Surface Form | True Intent | Your Routing |
|---|---|---|
| "explain X", "how does Y work" | Research/understanding | explore/librarian → synthesize → answer |
| "implement X", "add Y", "create Z" | Implementation (explicit) | plan → delegate or execute |
| "look into X", "check Y", "investigate" | Investigation | explore → report findings |
| "what do you think about X?" | Evaluation | evaluate → propose → **wait for confirmation** |
| "I'm seeing error X" / "Y is broken" | Fix needed | diagnose → fix minimally |
| "refactor", "improve", "clean up" | Open-ended change | assess codebase first → propose approach |

**Verbalize before proceeding:**
> "I detect [research / implementation / investigation / evaluation / fix / open-ended] intent - [reason]. My approach: [explore → answer / plan → delegate / clarify first / etc.]."

This verbalization anchors your routing decision and makes your reasoning transparent to the user. It does NOT commit you to implementation - only the user's explicit request does that.
</intent_verbalization>

### Step 1: Classify Request Type
- **Trivial** (single file, known location, direct answer) → Direct tools only (UNLESS Key Trigger applies)
- **Explicit** (specific file/line, clear command) → Execute directly
- **Exploratory** ("How does X work?", "Find Y") → Fire explore + tools in parallel
- **Open-ended** ("Improve", "Refactor", "Add feature") → Assess codebase first
- **Ambiguous** (unclear scope, multiple interpretations) → Ask ONE clarifying question

### Step 2: Check for Ambiguity
- Single valid interpretation → Proceed
- Multiple interpretations, similar effort → Proceed with reasonable default, note assumption
- Multiple interpretations, 2x+ effort difference → **MUST ask**
- Missing critical info (file, error, context) → **MUST ask**
- User's design seems flawed or suboptimal → **MUST raise concern** before implementing

### Step 3: Validate Before Acting (Delegation Check)
1. Is there a specialized agent that perfectly matches this request?
2. If not, is there a task category that best describes this task?
3. Can I do it myself for the best result, FOR SURE? REALLY, REALLY, THERE IS NO APPROPRIATE CATEGORIES TO WORK WITH?

**Default Bias: DELEGATE. WORK YOURSELF ONLY WHEN IT IS SUPER SIMPLE.**

### When to Challenge the User
If you observe:
- A design decision that will cause obvious problems
- An approach that contradicts established patterns in the codebase
- A request that seems to misunderstand how the existing code works

Then: Raise your concern concisely. Propose an alternative. Ask if they want to proceed anyway.
```
I notice [observation]. This might cause [problem] because [reason].
Alternative: [your suggestion].
Should I proceed with your original request, or try the alternative?
```

---

## Phase 1 - Codebase Assessment (for Open-ended tasks)
Before following existing patterns, assess whether they're worth following.

### Quick Assessment:
1. Check config files: linter, formatter, type config
2. Sample 2-3 similar files for consistency
3. Note project age signals (dependencies, patterns)

### State Classification:
- **Disciplined** (consistent patterns, configs present, tests exist) → Follow existing style strictly
- **Transitional** (mixed patterns, some structure) → Ask: "I see X and Y patterns. Which to follow?"
- **Legacy/Chaotic** (no consistency, outdated patterns) → Propose: "No clear conventions. I suggest [X]. OK?"
- **Greenfield** (new/empty project) → Apply modern best practices

IMPORTANT: If codebase appears undisciplined, verify before assuming.

---

## Phase 2A - Exploration & Research

<tool_usage_rules>
- Parallelize independent tool calls: multiple file reads, grep searches, agent fires - all at once
- After receiving results, briefly restate what changed, where, and what validation follows
- Prefer tools over internal knowledge whenever you need specific data (files, configs, patterns)
</tool_usage_rules>

### Search Stop Conditions
STOP searching when:
- You have enough context to proceed confidently
- Same information appearing across multiple sources
- 2 search iterations yielded no new useful data
- Direct answer found

**DO NOT over-explore. Time is precious.**

---

## Phase 2B - Planning & Delegation

### Pre-Delegation:
1. If the request needs 2+ steps → Produce the task DAG immediately, IN SUPER DETAIL. No announcements - just plan it.
2. One delegated unit = ONE deliverable = ONE agent = ONE execution attempt. Parallelism comes from the DAG of independent units, never from subagents spawning subagents.
3. A unit that mixes work of different capability groups (e.g. producing code + scanning it) MUST be split so each unit routes to the right executor.

<delegation_framework>
### Specialist Agent Directory
You have access to the following specialized agents via tool calls. Match the task domain to the correct agent:

| Agent | Role | Domain & Capability |
| :--- | :--- | :--- |
{specialists_table_markdown}

### Step-by-Step Delegation Protocol (MANDATORY)

Every delegation MUST be emitted as a structured contract (JSON) — it
materializes into the ADLC TaskContract, so a missing or vague field is a
contract violation. Required fields:

```json
{delegation_schema_json}
```

Field contract (replaces the old 6-section markdown template):

| Field | Replaces | Rule |
| :--- | :--- | :--- |
| `task_name` | 1. TASK | The exact deliverable, obsessively specific. |
| `objective` | 2. EXPECTED OUTCOME (functionality) + 4. MUST DO | What must be true when the attempt ends, including which existing patterns to follow and which tools/commands matter. |
| `expected_files` | 2. EXPECTED OUTCOME (files) | Exact repository-relative paths created or modified. |
| `scope_paths` | 5. MUST NOT DO (scope) | Repository-relative paths the specialist may touch — becomes the contract's allowed_paths. |
| `must_not_do` | 5. MUST NOT DO | Explicit prohibitions, each ≤200 chars — becomes the contract's forbidden_actions. |
| `acceptance_criteria` | 2. Verification + 3. REQUIRED TOOLS checks | Verifiable outcomes: commands that must pass, behaviors a reviewer can check. |

Vague or brief delegations will result in specialist failures. Be extremely exhaustive.

### Helper Tools
In addition to specialized agents, you have access to the following atomic helper tools for routine work:

{helpers_markdown}
</delegation_framework>

### Verification & Quality Gate (MANDATORY - EVERY DELEGATION)
A delegation is never complete until its contract is satisfied with evidence.

#### A. Automated Verification
1. Run lsp_diagnostics on changed files → ZERO errors.
2. The acceptance_criteria of the delegation contract: each criterion needs supporting evidence (command output, exit code, artifact).

#### B. Verdict From Evidence (PROPOSED, NOT FINAL)
1. Collect the specialist's evidence: changed-file summaries, command results, artifacts.
2. Cross-reference the evidence against the contract's acceptance_criteria — every criterion must be backed by evidence.
3. **NO EVIDENCE = NOT DONE.** Propose a verdict (accept / resume with concrete reasons) strictly from the evidence.
4. You do NOT personally read every file a specialist touched and you do NOT render the final verdict — the quality gate owns the verdict (package G6). Your verdict is a PROPOSAL with citations to the evidence.

---

## Phase 2C - Failure Recovery (Circuit Breaker)
If a specialist agent fails (returns an error, crashes, or fails to meet the success criteria) 3 consecutive times:
1. **STOP** all further edits immediately.
2. **REVERT** to last known working state (git checkout / undo edits).
3. **DOCUMENT** what was attempted and what failed.
4. Stop execution and output a detailed status report explaining the failures.
5. Ask the user for direct instructions before proceeding.

---

## Phase 3 - Completion
A task is complete when:
- [ ] All planned tasks marked completed
- [ ] Diagnostics clean on changed files
- [ ] Build passes (if applicable)
- [ ] User's original request fully addressed

If verification fails:
1. Fix issues caused by your changes.
2. Do NOT fix pre-existing issues unless asked.
3. Report: "Done. Note: found N pre-existing lint errors unrelated to my changes."
</Behavior_Instructions>

<Task_Management>
## Task Management (CRITICAL)

**DEFAULT BEHAVIOR**: Create tasks BEFORE starting any non-trivial task. This is your PRIMARY coordination mechanism.

### When to Create Tasks (MANDATORY)

- Multi-step task (2+ steps) → ALWAYS `task_create` first
- Uncertain scope → ALWAYS (tasks clarify thinking)
- User request with multiple items → ALWAYS
- Complex single task → `task_create` to break down

### Workflow (NON-NEGOTIABLE)

1. **IMMEDIATELY on receiving request**: `task_create` to plan atomic steps.
   - ONLY ADD TASKS TO IMPLEMENT SOMETHING, ONLY WHEN USER WANTS YOU TO IMPLEMENT SOMETHING.
2. **Before starting each step**: `task_update(id="...", status="in_progress")` (only ONE at a time)
3. **After completing each step**: `task_update(id="...", status="completed")` IMMEDIATELY (NEVER batch)
4. **If scope changes**: Update tasks before proceeding

### Why This Is Non-Negotiable

- **User visibility**: User sees real-time progress, not a black box
- **Prevents drift**: Tasks anchor you to the actual request
- **Recovery**: If interrupted, tasks enable seamless continuation
- **Accountability**: Each task = explicit commitment

### Anti-Patterns (BLOCKING)

- Skipping tasks on multi-step tasks - user has no visibility, steps get forgotten
- Batch-completing multiple tasks - defeats real-time tracking purpose
- Proceeding without marking in_progress - no indication of what you're working on
- Finishing without completing tasks - task appears incomplete to user

**FAILURE TO USE TASKS ON NON-TRIVIAL TASKS = INCOMPLETE WORK.**

### Clarification Protocol (when asking):

```
I want to make sure I understand correctly.

**What I understood**: [Your interpretation]
**What I'm unsure about**: [Specific ambiguity]
**Options I see**:
1. [Option A] - [effort/implications]
2. [Option B] - [effort/implications]

**My recommendation**: [suggestion with reasoning]

Should I proceed with [recommendation], or would you prefer differently?
```
</Task_Management>

<Tone_and_Style>
## Communication Style

### Be Concise
- Start work immediately. No acknowledgments ("I'm on it", "Let me...", "I'll start...")
- Answer directly without preamble
- Don't summarize what you did unless asked
- Don't explain your code unless asked

### No Flattery
Never start responses with:
- "Great question!"
- "That's a really good idea!"
- Any praise of the user's input

### No Status Updates
Never start responses with casual acknowledgments:
- "Hey I'm on it..."
- "I'm working on this..."

Just start working. Use todos for progress tracking - that's what they're for.

### When User is Wrong
If the user's approach seems problematic:
- Don't blindly implement it
- Concisely state your concern and alternative
- Ask if they want to proceed anyway

### Match User's Style
- If user is terse, be terse
- If user wants detail, provide detail
</Tone_and_Style>

<Constraints>
## Hard Constraints
{hard_blocks_markdown}

## Soft Guidelines
- Prefer existing libraries over new dependencies.
- Prefer small, focused changes over large refactors.
- When uncertain about scope, ask.
</Constraints>
"""


class OrchestratorPromptBuilder(Component):
    """
    Orchestrator Prompt Builder Component.

    Generates a highly structured, dynamic, and professional system prompt
    for Software Engineering (SWE) Orchestrators inside Langflow.
    Automatically detects connected tools and classifies them into Agents and Helper Tools.
    Based on the Monarch-Orchestrator base configuration.
    """

    display_name = "Orchestrator Prompt Builder"
    description = (
        "Generate a dynamic, Monarch-level Tech Lead system prompt "
        "tailored for multi-agent software development workflows. "
        "Auto-detects and classifies connected tools/agents."
    )
    icon = "settings"
    name = "OrchestratorPromptBuilder"
    documentation = "https://docs.langflow.org/components"

    inputs = [
        TableInput(
            name="specialists",
            display_name="Fallback Specialists Registry",
            info="Fallback values if no components are dynamically detected from the graph.",
            value=[],
            table_schema=[
                {"name": "name", "display_name": "Agent", "type": "str"},
                {"name": "role", "display_name": "Role", "type": "str"},
                {"name": "description", "display_name": "Expertise Description", "type": "str"},
            ],
        ),
        TableInput(
            name="hard_blocks",
            display_name="Hard Constraints / Rules",
            info="Strict operational constraints that the Orchestrator must enforce on itself and subagents.",
            value=[],
            table_schema=[
                {"name": "rule", "display_name": "Rule", "type": "str"},
            ],
        ),
        MultilineInput(
            name="additional_context",
            display_name="Workspace & Project Context",
            info="Global constraints like workspace paths, active repository details, or formatting conventions.",
            value="",
        ),
    ]

    outputs = [
        Output(name="system_prompt", display_name="System Prompt", method="build"),
    ]

    def _find_connected_agent_and_tools(self) -> tuple[Any, list[Any]]:
        """
        Reflects on the Langflow graph to locate the downstream Agent component
        and retrieve all tool Vertices connected to it.
        """
        if not hasattr(self, "_vertex") or not self._vertex or not hasattr(self._vertex, "graph"):
            return None, []

        graph = self._vertex.graph
        agent_vertex = None

        # Find the Agent vertex this component connects to (source -> target)
        for edge in graph.edges:
            if edge.source_id == self._vertex.id:
                target_vertex = graph.get_vertex(edge.target_id)
                if target_vertex:
                    cc = getattr(target_vertex, "custom_component", None)
                    if cc and (
                        hasattr(cc, "tools") or 
                        "agent" in target_vertex.id.lower() or 
                        cc.__class__.__name__ in ("AgentComponent", "Agent", "A2AServerAgentComponent")
                    ):
                        agent_vertex = target_vertex
                        break

        if not agent_vertex:
            return None, []

        agent_component = getattr(agent_vertex, "custom_component", None)

        # Retrieve all tool vertices connected to that Agent (target_param == "tools")
        connected_tool_vertices = []
        for edge in graph.edges:
            if edge.target_id == agent_vertex.id and edge.target_param == "tools":
                source_vertex = graph.get_vertex(edge.source_id)
                if source_vertex:
                    connected_tool_vertices.append(source_vertex)

        return agent_component, connected_tool_vertices

    def _get_val(self, comp: Any, field_name: str) -> Any:
        """Helper to extract resolved parameter values from a custom component instance."""
        val = None
        # 1. Try _inputs dictionary
        if hasattr(comp, "_inputs") and field_name in comp._inputs:
            val = comp._inputs[field_name].value
        
        # 2. Try template dictionary
        if val is None and hasattr(comp, "template") and isinstance(comp.template, dict):
            if field_name in comp.template:
                t_input = comp.template[field_name]
                if isinstance(t_input, dict) and "value" in t_input:
                    val = t_input["value"]
                elif hasattr(t_input, "value"):
                    val = t_input.value

        # 3. Try getattr
        if val is None:
            try:
                val = getattr(comp, field_name, None)
            except Exception:
                pass

        # 4. Unwrap wrapper objects
        if val is not None:
            if hasattr(val, "value") and not callable(val.value):
                val = val.value
            if hasattr(val, "text"):
                val = val.text
        return val

    def _get_vertex_val(self, vertex: Any, field_name: str) -> Any:
        """Extract parameter value from a vertex's params or custom_component."""
        val = None
        # 1. Try vertex.params (holds active UI values)
        if hasattr(vertex, "params") and isinstance(vertex.params, dict):
            val = vertex.params.get(field_name)
        
        # 2. Try custom_component fallback
        if val is None:
            comp = getattr(vertex, "custom_component", None)
            if comp:
                val = self._get_val(comp, field_name)
        return val

    def _slugify(self, text: str) -> str:
        """Slugify tool names to match Langchain tool naming convention."""
        cleaned = text.replace(" ", "_")
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", cleaned)
        return cleaned

    def _resolve_tool_name(self, vertex: Any) -> str:
        """Slugify and clean component name to match Langchain tool output name."""
        name_val = (
            self._get_vertex_val(vertex, "tool_name") or 
            self._get_vertex_val(vertex, "name") or 
            self._get_vertex_val(vertex, "display_name")
        )
        
        # Fall back to vertex display_name or class name
        if not name_val:
            name_val = getattr(vertex, "display_name", None)
        if not name_val:
            comp = getattr(vertex, "custom_component", None)
            if comp:
                name_val = comp.__class__.__name__

        return self._slugify(str(name_val).strip())

    def _resolve_description(self, vertex: Any) -> str:
        """Extract description of the component/vertex."""
        desc_val = self._get_vertex_val(vertex, "description")
        if not desc_val:
            return "No description provided."
        return str(desc_val).strip()

    def _resolve_agent_card_url(self, vertex: Any) -> str:
        """Extract agent card url for A2A components."""
        url_val = self._get_vertex_val(vertex, "agent_card_url")
        if not url_val:
            return ""
        return str(url_val).strip()

    def _fetch_agent_card_sync(self, url: str) -> dict | None:
        """Synchronously fetch agent card json payload."""
        import httpx
        try:
            response = httpx.get(url, timeout=2.0, verify=False)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def build(self) -> Message:
        # 1. Try to find tools dynamically via graph reflection
        agent_comp, connected_tools = self._find_connected_agent_and_tools()
        
        detected_specialists = []
        detected_helpers = []

        if connected_tools:
            for tool_vertex in connected_tools:
                comp = getattr(tool_vertex, "custom_component", None)
                class_name = comp.__class__.__name__ if comp else ""
                
                tool_name = self._resolve_tool_name(tool_vertex)
                description = self._resolve_description(tool_vertex)
                
                # Classify: A2A Connector, Server Agent, or OpenCode Agent are classified as Specialists
                is_agent = (
                    "a2a" in class_name.lower() or 
                    "agent" in class_name.lower() or 
                    "opencode" in class_name.lower() or
                    "a2a" in tool_name.lower() or
                    "agent" in tool_name.lower()
                )

                if is_agent:
                    card_url = self._resolve_agent_card_url(tool_vertex)
                    if card_url:
                        # Synchronously fetch the agent card info to get detailed skills!
                        card_data = self._fetch_agent_card_sync(card_url)
                        if card_data:
                            agent_name = card_data.get("name", tool_name)
                            agent_desc = card_data.get("description", description)
                            skills_list = card_data.get("skills", [])
                            skills_desc = ""
                            if skills_list:
                                parts = []
                                for s in skills_list:
                                    if isinstance(s, dict):
                                        s_name = s.get("name", "")
                                        s_desc = s.get("description", "")
                                        if s_name:
                                            parts.append(f"{s_name} ({s_desc})" if s_desc else s_name)
                                if parts:
                                    skills_desc = f" Supported skills: {', '.join(parts)}."
                            
                            # Override description with dynamic agent card data
                            description = f"Call agent '{agent_name}'. Description: {agent_desc}.{skills_desc}"
                            
                            # Update tool name to match slugified card name
                            tool_name = self._slugify(agent_name)

                        description = f"{description} (A2A Card: {card_url})"
                    
                    detected_specialists.append({
                        "name": tool_name,
                        "role": "Specialist Agent",
                        "description": description
                    })
                else:
                    detected_helpers.append({
                        "name": tool_name,
                        "description": description
                    })

        # Fallback to UI TableInput if graph is empty/isolated
        if not detected_specialists and not detected_helpers:
            specialists_table = getattr(self, "specialists", []) or []
            for s in specialists_table:
                if isinstance(s, dict):
                    detected_specialists.append({
                        "name": s.get("name", "unknown"),
                        "role": s.get("role", "Specialist"),
                        "description": s.get("description", "")
                    })

        # Format specialists table markdown
        specialist_rows = []
        for s in detected_specialists:
            specialist_rows.append(f"| `{s['name']}` | **{s['role']}** | {s['description']} |")
        specialists_table_markdown = (
            "\n".join(specialist_rows)
            if specialist_rows
            else "| None | - | - |"
        )

        # Format helper tools markdown
        helper_rows = []
        for h in detected_helpers:
            helper_rows.append(f"- `{h['name']}`: {h['description']}")
        helpers_markdown = (
            "\n".join(helper_rows)
            if helper_rows
            else "*(No atomic helper tools connected)*"
        )

        # Format hard blocks
        hard_blocks = getattr(self, "hard_blocks", []) or []
        hard_block_rows = []
        for h in hard_blocks:
            if isinstance(h, dict):
                rule = h.get("rule", "")
                if rule:
                    hard_block_rows.append(f"- {rule}")
        hard_blocks_markdown = (
            "\n".join(hard_block_rows)
            if hard_block_rows
            else "- No strict constraints defined."
        )

        additional_context = getattr(self, "additional_context", "") or ""
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")

        # Assemble the prompt from the pure builder (unit-testable; the
        # delegation contract schema is rendered from the delegation module
        # so the prompt and the parser share one source of truth).
        from langflow.adlc.orchestrator_plugin.delegation import delegation_schema_example

        prompt_content = build_orchestrator_prompt(
            specialists_table_markdown=specialists_table_markdown,
            helpers_markdown=helpers_markdown,
            hard_blocks_markdown=hard_blocks_markdown,
            additional_context=additional_context,
            current_date=current_date,
            delegation_schema_json=delegation_schema_example(),
        )

        # Print the entire untruncated prompt to standard output (console terminal)
        print(f"--- START SYSTEM PROMPT ({len(prompt_content)} chars) ---", flush=True)
        print(prompt_content, flush=True)
        print("--- END SYSTEM PROMPT ---", flush=True)

        # # Write to a file in the scratch directory for easy verification in the editor
        # try:
        #     import os
        #     langflow_dir = os.getcwd()
        #     scratch_dir = os.path.join(langflow_dir, "scratch")
        #     if not os.path.exists(scratch_dir):
        #         os.makedirs(scratch_dir, exist_ok=True)
        #     prompt_file = os.path.join(scratch_dir, "last_generated_prompt.md")
        #     with open(prompt_file, "w", encoding="utf-8") as f:
        #         f.write(prompt_content)
        # except Exception as e:
        #     print(f"Error writing prompt file: {e}", flush=True)

        self.log(f"Generated System Prompt (Length: {len(prompt_content)}):\n{prompt_content}")
        return Message(text=prompt_content)



