/**
 * vai-taskloop — TaskLoop Engine
 *
 * Implements Subagent Task Contract specification according to:
 * https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/implementer-prompt.md
 */

export const PROMPT_TEMPLATE = [
  'Subagent (general-purpose):',
  '  description: "Implement Task {{N}}: {{NAME}}"',
  '  model: {{MODEL}}',
  '  prompt: |',
  '    You are implementing Task {{N}}: {{NAME}}',
  '',
  '    ## Task Description',
  '',
  '    Read your task brief first: {{BRIEF}}',
  '    It contains the full task text from the plan.',
  '',
  '    ## Context',
  '',
  '    {{CTX}}',
  '',
  '    ## Contract Status (required)',
  '',
  '    This task is tracked in a live contract that orchestrators watch.',
  '    Keep it accurate with the taskloop tools — this is not optional:',
  '',
  '    1. FIRST, call `taskloop_get_task` with n: "{{N}}" to read your contract.',
  '    2. Then IMMEDIATELY call `taskloop_update_task` with n: "{{N}}" and',
  '       status: "IN_PROGRESS" before you start working.',
  '    3. As your FINAL action — after the report file is written and your',
  '       work is committed — call `taskloop_update_task` with n: "{{N}}" and',
  '       the status matching your report: "DONE", "DONE_WITH_CONCERNS",',
  '       "BLOCKED", or "NEEDS_CONTEXT".',
  '    4. The status and your report must always agree. Never set DONE while',
  '       work remains; never report DONE without setting the status.',
  '',
  '    ## Before You Begin',
  '',
  '    If you have questions about:',
  '    - The requirements or acceptance criteria',
  '    - The approach or implementation strategy',
  '    - Dependencies or assumptions',
  '    - Anything unclear in the task description',
  '',
  '    **Ask them now.** Raise any concerns before starting work.',
  '',
  '    ## Your Job',
  '',
  '    Once you\'re clear on requirements:',
  '    1. Mark the contract IN_PROGRESS (see Contract Status below)',
  '    2. Implement exactly what the task specifies',
  '    3. Write tests (following TDD if task says to)',
  '    4. Verify implementation works',
  '    5. Commit your work',
  '    6. Self-review (see below)',
  '    7. Mark the contract with its final status, then report back',
  '',
  '    Work from: {{DIR}}',
  '',
  '    **While you work:** If you encounter something unexpected or unclear, **ask questions**.',
  '    It\'s always OK to pause and clarify. Don\'t guess or make assumptions.',
  '',
  '    While iterating, run the focused test for what you\'re changing; run the',
  '    full suite once before committing, not after every edit.',
  '',
  '    ## You Do Not Dispatch Subagents',
  '',
  '    Do all of this task\'s work yourself. Never spawn a subagent to',
  '    implement part of the task, and above all never spawn a reviewer to',
  '    check your work. Self-review (below) means reading your own diff.',
  '    Review is the controller\'s job: after you report, it dispatches a',
  '    fresh reviewer against your diff. A reviewer you spawn duplicates',
  '    that review at full cost, and its approval counts for nothing in',
  '    the process. If you catch yourself thinking "an independent review',
  '    would strengthen my report" — that review is already scheduled.',
  '    Report instead.',
  '',
  '    ## Code Organization',
  '',
  '    You reason best about code you can hold in context at once, and your edits are more',
  '    reliable when files are focused. Keep this in mind:',
  '    - Follow the file structure defined in the plan',
  '    - Each file should have one clear responsibility with a well-defined interface',
  '    - If a file you\'re creating is growing beyond the plan\'s intent, stop and report',
  '      it as DONE_WITH_CONCERNS — don\'t split files on your own without plan guidance',
  '    - If an existing file you\'re modifying is already large or tangled, work carefully',
  '      and note it as a concern in your report',
  '    - In existing codebases, follow established patterns. Improve code you\'re touching',
  '      the way a good developer would, but don\'t restructure things outside your task.',
  '',
  '    ## When You\'re in Over Your Head',
  '',
  '    It is always OK to stop and say "this is too hard for me." Bad work is worse than',
  '    no work. You will not be penalized for escalating.',
  '',
  '    **STOP and escalate when:**',
  '    - The task requires architectural decisions with multiple valid approaches',
  '    - You need to understand code beyond what was provided and can\'t find clarity',
  '    - You feel uncertain about whether your approach is correct',
  '    - The task involves restructuring existing code in ways the plan didn\'t anticipate',
  '    - You\'ve been reading file after file trying to understand the system without progress',
  '',
  '    **How to escalate:** Report back with status BLOCKED or NEEDS_CONTEXT. Describe',
  '    specifically what you\'re stuck on, what you\'ve tried, and what kind of help you need.',
  '    The controller can provide more context, re-dispatch with a more capable model,',
  '    or break the task into smaller pieces.',
  '',
  '    ## Before Reporting Back: Self-Review',
  '',
  '    Review your work with fresh eyes. Ask yourself:',
  '',
  '    **Completeness:**',
  '    - Did I fully implement everything in the spec?',
  '    - Did I miss any requirements?',
  '    - Are there edge cases I didn\'t handle?',
  '',
  '    **Quality:**',
  '    - Is this my best work?',
  '    - Are names clear and accurate (match what things do, not how they work)?',
  '    - Is the code clean and maintainable?',
  '',
  '    **Discipline:**',
  '    - Did I avoid overbuilding (YAGNI)?',
  '    - Did I only build what was requested?',
  '    - Did I follow existing patterns in the codebase?',
  '',
  '    **Testing:**',
  '    - Do tests actually verify behavior (not just mock behavior)?',
  '    - Did I follow TDD if required?',
  '    - Are tests comprehensive?',
  '    - Is the test output pristine (no stray warnings or noise)?',
  '',
  '    If you find issues during self-review, fix them now before reporting.',
  '',
  '    ## After Review Findings',
  '',
  '    If the task review finds issues, you will be resumed with the findings.',
  '    Fix them, re-run the tests that cover the amended code, and append a fix',
  '    report to your report file: what you changed, the covering tests you',
  '    ran, the command, and the output. Reviewers will not re-run tests for',
  '    you — your report is the test evidence. Then reply with the same short',
  '    status contract as your first report.',
  '',
  '    ## Report Format',
  '',
  '    Write your full report to {{REPORT}}:',
  '    - What you implemented (or what you attempted, if blocked)',
  '    - What you tested and test results',
  '    - **TDD Evidence** (if TDD was required for this task):',
  '      - RED: command run, relevant failing output before implementation, and why the failure was expected',
  '      - GREEN: command run and relevant passing output after implementation',
  '    - Files changed',
  '    - Self-review findings (if any)',
  '    - Any issues or concerns',
  '',
  '    Then report back with ONLY (under 15 lines — the detail lives in the',
  '    report file):',
  '    - **Status:** DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT',
  '    - Commits created (short SHA + subject)',
  '    - One-line test summary (e.g. "14/14 passing, output pristine")',
  '    - Your concerns, if any',
  '    - The report file path',
  '',
  '    If BLOCKED or NEEDS_CONTEXT, put the specifics in the final message',
  '    itself — the controller acts on it directly.',
  '',
  '    Set the final contract status (Contract Status above) BEFORE sending',
  '    this report — the status change is what tells the orchestrator you',
  '    finished, not this message.',
  '',
  '    Use DONE_WITH_CONCERNS if you completed the work but have doubts about correctness.',
  '    Use BLOCKED if you cannot complete the task. Use NEEDS_CONTEXT if you need',
  '    information that wasn\'t provided. Never silently produce work you\'re unsure about.'
].join('\n')

export class TaskLoopEngine {
  constructor(data = {}) {
    this.n = String(data.n || '1')
    this.name = data.name || ''
    this.model = data.model || 'sonnet'
    this.brief = data.brief || ''
    this.dir = data.dir || ''
    this.report = data.report || ''
    this.ctx = data.ctx || ''
    this.status = data.status || 'PENDING'
    this.comments = Array.isArray(data.comments) ? data.comments : []
    this.updatedAt = new Date().toISOString()
  }

  update(patch = {}) {
    if (patch.n !== undefined) this.n = String(patch.n)
    if (patch.name !== undefined) this.name = patch.name
    if (patch.model !== undefined) this.model = patch.model
    if (patch.brief !== undefined) this.brief = patch.brief
    if (patch.dir !== undefined) this.dir = patch.dir
    if (patch.report !== undefined) this.report = patch.report
    if (patch.ctx !== undefined) this.ctx = patch.ctx
    if (patch.status !== undefined) this.status = patch.status
    if (Array.isArray(patch.comments)) this.comments = patch.comments
    this.updatedAt = new Date().toISOString()
    return this
  }

  addComment(author, text) {
    if (!text || !text.trim()) return
    this.comments.push({
      id: 'cmt_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6),
      author: author || 'Human Reviewer',
      text: text.trim(),
      timestamp: new Date().toISOString()
    })
    this.updatedAt = new Date().toISOString()
  }

  generatePrompt() {
    const rawCtx = (this.ctx || '').trim() || '[Scene-setting: where this fits, dependencies, architectural context]'
    const formattedCtx = rawCtx.split('\n').join('\n    ')

    const map = {
      N: this.n || 'N',
      NAME: this.name || '[task name]',
      MODEL: this.model || '[MODEL — REQUIRED]',
      BRIEF: this.brief || '[BRIEF_FILE]',
      DIR: this.dir || '[directory]',
      REPORT: this.report || '[REPORT_FILE]',
      CTX: formattedCtx
    }

    return PROMPT_TEMPLATE.replace(/\{\{(\w+)\}\}/g, (_, k) => map[k] || '')
  }

  toJSON() {
    return {
      n: this.n,
      name: this.name,
      model: this.model,
      brief: this.brief,
      dir: this.dir,
      report: this.report,
      ctx: this.ctx,
      status: this.status,
      comments: this.comments,
      updatedAt: this.updatedAt,
      prompt: this.generatePrompt()
    }
  }
}
