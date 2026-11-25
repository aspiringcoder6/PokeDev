/**
 * vai-taskloop â€” AI Agent Tools
 *
 * Provides atomic tools for AI Agents to inspect, create, update, and export
 * subagent task contracts according to the Subagent-Driven Development standard.
 */

import fs from 'node:fs'
import path from 'node:path'
import { TASK_STATUSES } from './goal-bridge.js'
import { TaskLoopEngine } from './engine.js'

function getSessionId(exec) {
  const id = exec?.agent?.session?.id
  return typeof id === 'string' && id ? id : 'default'
}

function getWorkspaceDir(exec) {
  const cwd = exec?.agent?.session?.header?.cwd
  if (typeof cwd === 'string' && cwd) return cwd
  return process.cwd() || '/app/workspace'
}

function taskStoreDir(exec) {
  return path.join(getWorkspaceDir(exec), 'taskloop')
}

const TASK_FILE_PATTERN = /^task-\d+\.task\.json$/

function readTaskFile(exec, n) {
  try {
    const p = path.join(taskStoreDir(exec), `task-${n || '1'}.task.json`)
    if (!fs.existsSync(p)) return null
    return JSON.parse(fs.readFileSync(p, 'utf8'))
  } catch {
    return null
  }
}

function readLatestTaskFile(dir) {
  try {
    if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return null
    const files = fs.readdirSync(dir).filter(f => TASK_FILE_PATTERN.test(f)).sort()
    if (files.length === 0) return null
    return JSON.parse(fs.readFileSync(path.join(dir, files[files.length - 1]), 'utf8'))
  } catch {
    return null
  }
}

function loadPersistedContract(exec) {
  const cwd = getWorkspaceDir(exec)
  const dirs = [
    path.join(cwd, 'taskloop'),
    path.join(cwd, 'tasks'),
    cwd,
    '/app/workspace/tasks',
    '/app/workspace'
  ]
  for (const dir of dirs) {
    const data = readLatestTaskFile(dir)
    if (data) return data
  }
  return null
}

function ensureEngine(sessionMap, exec, bridge) {
  const sessionId = getSessionId(exec)
  let engine = sessionMap.get(sessionId)
  if (!engine) {
    const canonical = readLatestTaskFile(taskStoreDir(exec))
    const persisted = canonical || loadPersistedContract(exec)
    engine = persisted
      ? new TaskLoopEngine(persisted)
      : new TaskLoopEngine({ n: '1', model: 'sonnet' })
    sessionMap.set(sessionId, engine)
    bridge?.syncGoal?.(exec?.agent, engine, 'hydrate')
    return engine
  }
  // File-as-truth against THIS task's own file only, so concurrent
  // contracts (task-3 vs task-4) never steal the active pointer.
  const own = readTaskFile(exec, engine.n)
  if (own && own.updatedAt && engine.updatedAt && own.updatedAt > engine.updatedAt) {
    engine = new TaskLoopEngine(own)
    sessionMap.set(sessionId, engine)
    bridge?.syncGoal?.(exec?.agent, engine, 'file-newer')
  }
  return engine
}

/** Resolve the engine for an explicit task number, or null when absent. */
function resolveByN(sessionMap, exec, n) {
  const sessionId = getSessionId(exec)
  const active = sessionMap.get(sessionId)
  if (active && active.n === String(n)) return active
  const existing = readTaskFile(exec, n)
  if (!existing) return null
  const engine = new TaskLoopEngine(existing)
  sessionMap.set(sessionId, engine)
  return engine
}

function autoSave(engine, exec) {
  try {
    if (!engine) return
    const dir = taskStoreDir(exec)
    fs.mkdirSync(dir, { recursive: true })
    const fileName = `task-${engine.n || '1'}.task.json`
    fs.writeFileSync(path.join(dir, fileName), JSON.stringify(engine.toJSON(), null, 2), 'utf8')
    engine.storeDir = dir
  } catch (err) {
    console.warn('[vai-taskloop] autoSave error:', err)
  }
}

function textCard(...lines) {
  return [{ type: 'text', text: lines.filter(Boolean).join('\n') }]
}

function safe(obj) {
  return JSON.parse(JSON.stringify(obj))
}

function unwrap(args) {
  if (args && typeof args === 'object') {
    for (const key of ['task', 'params', 'data', 'args']) {
      if (args[key] && typeof args[key] === 'object' && !Array.isArray(args[key])) {
        return args[key]
      }
    }
  }
  return args || {}
}

export function registerTools(ctx, sessionMap, eventBus, bridge) {

  // â”€â”€ 1. taskloop_create_task â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  ctx.tools?.register({
    name: 'taskloop_create_task',
    description: [
      'Create or initialize a Subagent Task Contract.',
      'Example: { "n": "1", "name": "ThÃªm API auth", "model": "sonnet", "brief": "docs/plans/task-1-brief.md", "dir": "/app/workspace", "report": "reports/task-1-report.md", "ctx": "Task ná»‘i tiáº¿p Task 0..." }',
      'Updates the live Web Form and generates implementer prompt.'
    ].join(' '),
    parameters: {
      type: 'object',
      properties: {
        n:      { type: 'string', description: 'Task sequence number (N), e.g. "1"' },
        name:   { type: 'string', description: 'Task name/title, e.g. "Add login API"' },
        model:  { type: 'string', description: 'Target subagent model: haiku | sonnet | opus | deepseek-chat' },
        brief:  { type: 'string', description: 'Task brief path (BRIEF_FILE), e.g. "docs/plans/task-1-brief.md"' },
        dir:    { type: 'string', description: 'Working directory, e.g. "/app/workspace"' },
        report: { type: 'string', description: 'Report file path (REPORT_FILE), e.g. "reports/task-1-report.md"' },
        ctx:    { type: 'string', description: 'Architectural context notes (where it fits, dependencies)' },
        status: { type: 'string', description: 'Initial status: PENDING | IN_PROGRESS | DONE' }
      },
      required: ['n', 'name', 'model'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (args, value) => textCard(`Task Contract #${value?.task?.n || args?.n || '?'} "${value?.task?.name || args?.name || ''}" created successfully.`),
    },
    async execute(args, exec) {
      const s = unwrap(args)
      const sessionId = getSessionId(exec)
      if (s.status && !TASK_STATUSES.includes(s.status)) {
        return safe({ ok: false, error: `Invalid status "${s.status}". Allowed: ${TASK_STATUSES.join(' | ')}` })
      }

      // Re-creating an existing contract MERGES into it (status is kept
      // unless explicitly provided) instead of resetting it to PENDING.
      const existing = readTaskFile(exec, s.n || '1')
      const engine = existing
        ? new TaskLoopEngine({ ...existing, ...s, status: s.status || existing.status || 'PENDING' })
        : new TaskLoopEngine({
          n: s.n || '1',
          name: s.name || '',
          model: s.model || 'sonnet',
          brief: s.brief || '',
          dir: s.dir || '',
          report: s.report || '',
          ctx: s.ctx || '',
          status: s.status || 'PENDING'
        })

      sessionMap.set(sessionId, engine)
      const json = engine.toJSON()
      autoSave(engine, exec)
      bridge?.syncGoal?.(exec?.agent, engine, existing ? 'recreate' : 'create')
      eventBus.broadcast(sessionId, existing ? 'task_updated' : 'task_created', json)

      return safe({
        ok: true,
        reused: Boolean(existing),
        task: json,
        prompt: engine.generatePrompt()
      })
    }
  })

  // â”€â”€ 2. taskloop_get_task â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  ctx.tools?.register({
    name: 'taskloop_get_task',
    description: 'Retrieve task contract details, status, and generated implementer prompt. Pass "n" to read a specific task; omit it for the currently active contract.',
    parameters: {
      type: 'object',
      properties: {
        n: { type: 'string', description: 'Task number to read, e.g. "3". Omit for the active contract.' }
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (args, value) => textCard(`Task #${value?.task?.n ?? '?'}: "${value?.task?.name ?? ''}" [${value?.task?.status ?? '?'}]`),
    },
    async execute(args, exec) {
      const s = unwrap(args)
      const engine = s.n ? resolveByN(sessionMap, exec, s.n) : ensureEngine(sessionMap, exec, bridge)
      if (!engine) {
        return safe({ ok: false, error: `No contract task-${s.n}.task.json found in ${taskStoreDir(exec)}.` })
      }
      const json = engine.toJSON()
      return safe({
        ok: true,
        task: json,
        prompt: engine.generatePrompt()
      })
    }
  })

  // â”€â”€ 3. taskloop_update_task â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  ctx.tools?.register({
    name: 'taskloop_update_task',
    description: 'Update fields of a task contract (e.g. status, brief, context, report). Pass "n" to update a specific task; omit it to update the currently active contract.',
    parameters: {
      type: 'object',
      properties: {
        n:      { type: 'string', description: 'Task number to update, e.g. "4". Omit for the active contract.' },
        name:   { type: 'string', description: 'New task name' },
        status: { type: 'string', description: 'New status: PENDING | IN_PROGRESS | DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT' },
        model:  { type: 'string', description: 'Subagent model' },
        brief:  { type: 'string', description: 'Brief file path' },
        dir:    { type: 'string', description: 'Working directory' },
        report: { type: 'string', description: 'Report file path' },
        ctx:    { type: 'string', description: 'Context notes' }
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (args, value) => textCard(`Task #${value?.task?.n ?? '?'} updated. Status: ${value?.task?.status ?? '?'}`),
    },
    async execute(args, exec) {
      const s = unwrap(args)
      const sessionId = getSessionId(exec)
      if (s.status && !TASK_STATUSES.includes(s.status)) {
        return safe({ ok: false, error: `Invalid status "${s.status}". Allowed: ${TASK_STATUSES.join(' | ')}` })
      }
      let engine
      if (s.n) {
        engine = resolveByN(sessionMap, exec, s.n)
        if (!engine) {
          return safe({ ok: false, error: `No contract task-${s.n}.task.json found in ${taskStoreDir(exec)}.` })
        }
        engine.update(s)
        sessionMap.set(sessionId, engine)
      } else {
        engine = sessionMap.get(sessionId)
        if (!engine) {
          const canonical = readLatestTaskFile(taskStoreDir(exec))
          const persisted = canonical || loadPersistedContract(exec)
          engine = persisted
            ? new TaskLoopEngine({ ...persisted, ...s })
            : new TaskLoopEngine(s)
          sessionMap.set(sessionId, engine)
        } else {
          engine.update(s)
        }
      }
      const json = engine.toJSON()
      autoSave(engine, exec)
      bridge?.syncGoal?.(exec?.agent, engine, 'update')
      eventBus.broadcast(sessionId, 'task_updated', json)

      return safe({
        ok: true,
        task: json
      })
    }
  })

  // â”€â”€ 4. taskloop_add_comment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  ctx.tools?.register({
    name: 'taskloop_add_comment',
    description: 'Add a review note, question, or comment to the task contract.',
    parameters: {
      type: 'object',
      properties: {
        author: { type: 'string', description: 'Commenter name (e.g. "Reviewer Subagent" or "Human")' },
        text:   { type: 'string', description: 'Comment / review message' }
      },
      required: ['text'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (args, value) => {
        const comments = Array.isArray(value?.task?.comments) ? value.task.comments : []
        const last = comments[comments.length - 1]
        return textCard(`Comment #${value?.commentsCount ?? comments.length} added: "${(last?.text || '').slice(0, 50)}..."`)
      },
    },
    async execute(args, exec) {
      const s = unwrap(args)
      const engine = ensureEngine(sessionMap, exec, bridge)

      engine.addComment(s.author || 'Agent', s.text)
      const json = engine.toJSON()
      autoSave(engine, exec)
      eventBus.broadcast(sessionId, 'comment_added', json)

      return safe({
        ok: true,
        commentsCount: engine.comments.length,
        task: json
      })
    }
  })

  // â”€â”€ 5. taskloop_export_prompt â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  ctx.tools?.register({
    name: 'taskloop_export_prompt',
    description: 'Export the complete implementer prompt string ready to pass to invoke_subagent.',
    parameters: { type: 'object', properties: {} },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (args, value) => textCard(`Generated prompt (${value?.prompt?.length || 0} chars)`),
    },
    async execute(args, exec) {
      const engine = ensureEngine(sessionMap, exec, bridge)

      return safe({
        ok: true,
        prompt: engine.generatePrompt()
      })
    }
  })
}
