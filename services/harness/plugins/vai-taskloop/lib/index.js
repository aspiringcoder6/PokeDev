/**
 * vai-taskloop — Host Plugin Entrypoint
 * 
 * DeepSeek Harness Plugin for Subagent Task Loop & Contract Management.
 * Provides atomic tools for Agents and realtime SSE streaming to Web Client.
 */

import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { attachGoalBridge } from './goal-bridge.js'
import { TaskLoopEventBus } from './events.js'
import { registerRoutes } from './routes.js'
import { registerTools } from './tools.js'

export const name = 'vai-taskloop'
export const inject = ['tools', 'skills']

const SKILL_MD_URL = new URL('../skills/vai-taskloop/SKILL.md', import.meta.url)
const SKILL_RESOURCE_BASE = { kind: 'directory', path: fileURLToPath(new URL('../skills/vai-taskloop/', import.meta.url)) }
const SKILL_RANK = 400

function parseFrontmatter(raw) {
  const block = /^---\r?\n([\s\S]*?)\r?\n---/.exec(raw)?.[1] ?? ''
  const name = /^name:\s*(.+)$/m.exec(block)?.[1]?.trim() ?? 'vai-taskloop'
  const descriptionLines = []
  let inDescription = false
  for (const line of block.split(/\r?\n/)) {
    if (/^description:\s*>/.test(line)) {
      inDescription = true
    } else if (inDescription) {
      if (/^\s/.test(line)) descriptionLines.push(line.trim())
      else inDescription = false
    }
  }
  return { name, description: descriptionLines.join(' ').trim() }
}

function createSkillProvider() {
  const invocation = { modelInvocable: true, userInvocable: true }
  return {
    name: 'vai-taskloop',
    async list() {
      const raw = await readFile(SKILL_MD_URL, 'utf8')
      const { name, description } = parseFrontmatter(raw)
      return [{
        name,
        description,
        invocation,
        provider: 'vai-taskloop',
        source: 'plugin',
        resourceBase: SKILL_RESOURCE_BASE,
        rank: SKILL_RANK,
        locator: SKILL_MD_URL,
      }]
    },
    async get(candidate) {
      const content = await readFile(SKILL_MD_URL, 'utf8')
      const { description } = parseFrontmatter(content)
      return {
        name: candidate.name,
        description,
        invocation,
        provider: 'vai-taskloop',
        source: 'plugin',
        resourceBase: SKILL_RESOURCE_BASE,
        content,
      }
    },
  }
}

export function apply(ctx, config) {
  const sessionMap = new Map() // sessionId -> TaskLoopEngine
  const eventBus = new TaskLoopEventBus()

  // Register HTTP routes when webServer service is available
  ctx.inject(['webServer', 'connection'], (webCtx) => {
    webCtx.effect(() => registerRoutes(webCtx, sessionMap, eventBus), 'vai-taskloop: http routes')
    webCtx.logger?.info?.('vai-taskloop: HTTP API mounted at /api/taskloop')
  })

  // Self-register the bundled skill — SYNCHRONOUSLY during apply() as the
  // skill subsystem requires (docs/subsystems/skills.md: "plugins register
  // synchronously during apply()"). Plugin-contained, no core config edits.
  ctx.skills.registerProvider(() => createSkillProvider())

  // Register the 5 taskloop agent tools
  const goalBridge = attachGoalBridge(ctx, sessionMap)
  registerTools(ctx, sessionMap, eventBus, goalBridge)
  ctx.logger?.info?.('vai-taskloop: 5 Agent TaskLoop Tools registered successfully')
}
