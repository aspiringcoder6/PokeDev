/**
 * vai-taskloop — Goal Bridge & Auto-Heal
 *
 * Bridges the task contract status to the DSH same-session goal subsystem:
 * - status IN_PROGRESS            -> create/resume an armed goal (the goal-round
 *                                    driver keeps the agent working until done)
 * - status DONE/DONE_WITH_CONCERNS-> goals.complete
 * - status BLOCKED/NEEDS_CONTEXT  -> goals.block
 * - status PENDING                -> goals.pause
 *
 * Auto-heal: transient provider errors disarm the goal while its phase stays
 * 'active'. While the contract status is IN_PROGRESS, the bridge re-arms the
 * goal with exponential backoff (15s base, x2, capped at 5 minutes, max 10
 * attempts). The attempt budget resets as soon as the agent runs again.
 */

export const TASK_STATUSES = ['PENDING', 'IN_PROGRESS', 'DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT']

const GOAL_MAX_ROUNDS = 64
const HEAL_MAX_ATTEMPTS = 10
const HEAL_BACKOFF_BASE_MS = 15000
const HEAL_BACKOFF_CAP_MS = 300000

const TRANSIENT_ERROR_PATTERN = /429|rate[ ._-]?limit|too many requests|5\d{2}|internal server error|bad gateway|service unavailable|gateway timeout|overloaded|capacity|timeout|timed out|econnreset|econnrefused|epipe|socket hang up|network|fetch failed/i

function isTransientError(error) {
  const text = String(error?.message || error || '')
  return TRANSIENT_ERROR_PATTERN.test(text)
}

function goalRef(view) {
  return { id: view.id, revision: view.revision }
}

function objectiveOf(engine) {
  return [
    `Complete Task #${engine.n || '1'}: ${engine.name || '(untitled task)'}.`,
    engine.report ? `Write the report to ${engine.report}.` : '',
    'The task contract file in the taskloop directory is the source of truth. Keep its status current with taskloop_update_task; gather evidence before marking the goal complete, and the objective is achieved only when the contract status is DONE or DONE_WITH_CONCERNS.',
  ].filter(Boolean).join(' ')
}

export function attachGoalBridge(ctx, sessionMap) {
  let goals = null
  try {
    ctx.inject(['goals'], (goalCtx) => {
      goals = goalCtx.get('goals')
      console.log('[vai-taskloop] goal bridge attached to @deepseek-ai/dsh-goal')
    })
  } catch (e) {
    console.warn(`[vai-taskloop] goals service unavailable, goal bridge disabled: ${e.message}`)
  }

  function goalsService() {
    if (goals) return goals
    try {
      goals = ctx.get('goals')
    } catch {
      goals = null
    }
    return goals
  }

  const lastSynced = new Map() // sessionId -> last synced contract status
  const heal = new Map()       // sessionId -> { attempts, timer, resetTimer }

  function syncGoal(agent, engine, cause) {
    const service = goalsService()
    if (!service || !agent || !engine) return
    const sid = agent?.session?.id || 'default'
    const status = engine.status || 'PENDING'
    if (lastSynced.get(sid) === status) return
    lastSynced.set(sid, status)
    try {
      const view = service.get(agent)
      if (status === 'IN_PROGRESS') {
        if (!view || view.phase === 'complete') {
          service.create(agent, { objective: objectiveOf(engine), maxGoalRounds: GOAL_MAX_ROUNDS })
          console.log(`[vai-taskloop] goal created+armed (status=${status}, cause=${cause}) sid=${sid}`)
        } else if (view.phase !== 'active' || view.activation === 'disarmed') {
          service.resume(agent, goalRef(view))
          console.log(`[vai-taskloop] goal resumed (phase=${view.phase}, cause=${cause}) sid=${sid}`)
        }
      } else if (status === 'DONE' || status === 'DONE_WITH_CONCERNS') {
        if (view && view.phase !== 'complete') {
          service.complete(agent, goalRef(view))
          console.log(`[vai-taskloop] goal completed (status=${status}, cause=${cause}) sid=${sid}`)
        }
      } else if (status === 'BLOCKED' || status === 'NEEDS_CONTEXT') {
        if (view && view.phase === 'active') {
          service.block(agent, goalRef(view), { code: status.toLowerCase(), message: `Task contract status is ${status}` })
          console.log(`[vai-taskloop] goal blocked (status=${status}, cause=${cause}) sid=${sid}`)
        }
      } else if (status === 'PENDING') {
        if (view && view.phase === 'active') {
          service.pause(agent, goalRef(view))
          console.log(`[vai-taskloop] goal paused (status=PENDING, cause=${cause}) sid=${sid}`)
        }
      }
    } catch (e) {
      console.warn(`[vai-taskloop] goal sync (cause=${cause}) failed: ${e.message}`)
    }
  }

  function clearHeal(sid) {
    const st = heal.get(sid)
    if (!st) return
    if (st.timer) clearTimeout(st.timer)
    if (st.resetTimer) clearTimeout(st.resetTimer)
    heal.delete(sid)
  }

  /** Extract the provider's "Limit resets at: <date>" hint from a 429 body. */
  function parseResetAt(error) {
    const text = String(error?.message || error || '')
    const raw = /Limit resets at:\s*([^"\n]+?)[.,;]?\s*(?:["\n]|$)/i.exec(text)?.[1]?.trim()
    if (!raw) return null
    const normalized = raw
      .replace(/\s*UTC\s*$/i, 'Z')
      .replace(/^(\d{4}-\d{2}-\d{2})\s+/, '$1T')
    const ts = Date.parse(normalized)
    return Number.isFinite(ts) ? ts : null
  }

  function attemptHealResume(agent, sid, label) {
    const service = goalsService()
    if (!service) return
    const engine = sessionMap.get(sid)
    if (!engine || engine.status !== 'IN_PROGRESS') {
      console.log(`[vai-taskloop] auto-heal skipped (${label}): task no longer IN_PROGRESS sid=${sid}`)
      clearHeal(sid)
      return
    }
    let view
    try {
      view = service.get(agent)
    } catch (e) {
      console.warn(`[vai-taskloop] auto-heal (${label}) goals.get failed: ${e.message}`)
      return
    }
    if (!view) {
      console.log(`[vai-taskloop] auto-heal skipped (${label}): no current goal sid=${sid}`)
      return
    }
    if (view.phase !== 'active' && view.phase !== 'paused') {
      // 'blocked' (model/human-declared) and 'complete' stay untouched.
      console.log(`[vai-taskloop] auto-heal skipped (${label}): goal phase=${view.phase} sid=${sid}`)
      return
    }
    if (view.phase === 'active' && view.activation === 'armed') return
    try {
      service.resume(agent, goalRef(view))
      console.log(`[vai-taskloop] auto-heal resumed goal (phase=${view.phase}, ${label}) sid=${sid}`)
    } catch (e) {
      console.warn(`[vai-taskloop] auto-heal (${label}) resume failed: ${e.message}`)
    }
  }

  function scheduleHeal(agent, sid, resetAt) {
    const st = heal.get(sid) || { attempts: 0, timer: null, resetTimer: null }
    heal.set(sid, st)
    const exhausted = st.attempts >= HEAL_MAX_ATTEMPTS
    const delay = Math.min(HEAL_BACKOFF_BASE_MS * (2 ** st.attempts), HEAL_BACKOFF_CAP_MS)

    if (!exhausted) {
      if (st.timer) return
      st.attempts += 1
      st.timer = setTimeout(() => {
        st.timer = null
        attemptHealResume(agent, sid, `backoff attempt ${st.attempts}/${HEAL_MAX_ATTEMPTS}`)
      }, delay)
      console.log(`[vai-taskloop] auto-heal scheduled in ${Math.round(delay / 1000)}s (attempt ${st.attempts}/${HEAL_MAX_ATTEMPTS}) sid=${sid}`)
    } else {
      console.warn(`[vai-taskloop] auto-heal ladder exhausted (${HEAL_MAX_ATTEMPTS} attempts) sid=${sid}`)
    }

    // Provider quota windows can outlast the backoff ladder: when the error
    // carries a "Limit resets at" hint, wake once just after the reset.
    if (resetAt) {
      const resetDelay = Math.max(resetAt + 2000 - Date.now(), 5000)
      if (resetDelay <= 2 * 60 * 60 * 1000 && !st.resetTimer) {
        st.resetTimer = setTimeout(() => {
          st.resetTimer = null
          attemptHealResume(agent, sid, 'rate-limit reset')
        }, resetDelay)
        console.log(`[vai-taskloop] auto-heal also scheduled at rate-limit reset (+${Math.round(resetDelay / 1000)}s) sid=${sid}`)
      }
    }
  }

  ctx.on('agent/error', ({ agent, error } = {}) => {
    try {
      if (!agent) return
      const sid = agent?.session?.id
      const engine = sid && sessionMap.get(sid)
      if (!engine || engine.status !== 'IN_PROGRESS') return
      if (!goalsService()) return
      if (!isTransientError(error)) {
        console.warn(`[vai-taskloop] non-transient agent error, auto-heal skipped sid=${sid}: ${String(error?.message || error).slice(0, 120)}`)
        return
      }
      scheduleHeal(agent, sid, parseResetAt(error))
    } catch (e) {
      console.warn(`[vai-taskloop] auto-heal check failed: ${e.message}`)
    }
  })

  ctx.on('agent/status', ({ agent, status } = {}) => {
    try {
      const sid = agent?.session?.id
      if (!sid) return
      if (status && status !== 'idle') {
        // A round actually started — the error is recovered, reset the budget.
        const st = heal.get(sid)
        if (st && st.attempts > 0) console.log(`[vai-taskloop] agent running again, auto-heal budget reset sid=${sid}`)
        clearHeal(sid)
        return
      }
      // Idle reconciler: catch status changes made outside the tools
      // (viewer buttons, manual file edits) and converge the goal.
      const engine = sessionMap.get(sid)
      if (engine) syncGoal(agent, engine, 'idle-reconcile')
    } catch (e) {
      console.warn(`[vai-taskloop] status reconcile failed: ${e.message}`)
    }
  })

  return { syncGoal }
}
