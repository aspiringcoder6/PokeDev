import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { SessionMemoryClient } from './session-memory.js'

export const LOOP_ROOT = '/api/v1/pokedev-services/product-loops'
export const PROPOSE_TOOL = 'pokedev_loop_propose'
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/
const pathOK = p => typeof p === 'string' && /^[A-Za-z0-9_/-]+\.py$/.test(p)
  && !p.split('/').some(part => !part || part === '..' || part.startsWith('.'))
const hash = value => createHash('sha256').update(value).digest('hex')
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(k => [k, canonical(value[k])])) : value
export const commandDigest = c => hash(JSON.stringify(canonical(c)))
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
function fail(code) { throw new Error(code) }
export function validateLoop(c) {
  if (!c || Object.keys(c).sort().join(',') !== 'base_commit,checks,files,goal,loop_id,max_iterations,scope_id,writable_paths'
      || !UUID.test(c.loop_id) || !/^[a-f0-9]{64}$/.test(c.scope_id) || !/^[a-f0-9]{40}$/.test(c.base_commit)
      || typeof c.goal !== 'string' || !c.goal.trim() || c.goal.length > 18000
      || !Number.isInteger(c.max_iterations) || c.max_iterations < 1 || c.max_iterations > 3
      || !Array.isArray(c.writable_paths) || !c.writable_paths.length || c.writable_paths.length > 8
      || new Set(c.writable_paths).size !== c.writable_paths.length || !c.writable_paths.every(pathOK)
      || !c.files || Array.isArray(c.files) || Object.keys(c.files).length > 12
      || Object.entries(c.files).some(([p, text]) => !pathOK(p) || typeof text !== 'string')
      || !c.writable_paths.every(p => Object.hasOwn(c.files, p))
      || !Array.isArray(c.checks) || !c.checks.length || c.checks.length > 4
      || c.checks.some(check => Object.keys(check).sort().join(',') !== 'check_id,test_path,timeout_ms'
        || !/^[a-z][a-z0-9_]{0,63}$/.test(check.check_id) || !pathOK(check.test_path)
        || !Object.hasOwn(c.files, check.test_path) || c.writable_paths.includes(check.test_path)
        || !Number.isInteger(check.timeout_ms) || check.timeout_ms < 100 || check.timeout_ms > 60000)
      || Object.keys(c.files).some(p => !c.writable_paths.includes(p) && !c.checks.some(x => x.test_path === p))
      || JSON.stringify(c).length > 120000) fail('LOOP_COMMAND_INVALID')
  if (Object.keys(c.files).some(p => p.startsWith('pokedev-'))) fail('LOOP_COMMAND_INVALID')
  return structuredClone(c)
}

export class ProductLoops {
  constructor(ctx, { dataDir, workspaceDir, model = { provider: 'netmind', model: 'zai-org/GLM-5.3-Flash' }, createUserMessage }) {
    this.ctx = ctx; this.root = dataDir; this.workspaces = workspaceDir; this.model = model
    this.message = createUserMessage; this.jobs = new Map(); this.handles = new Map(); this.controllers = new Map()
  }
  capabilities() {
    const required = ['sandbox_create', 'sandbox_status', 'sandbox_write_file', 'sandbox_shell',
      'taskloop_create_task', 'taskloop_update_task', 'taskloop_get_task', 'memory_health']
    const missing = required.filter(n => !this.ctx.tools.get(n)?.execute)
    return { version: '0.1.0', ready: !this.initializationError && !missing.length && !!this.ctx.agents?.create && !!this.goals() && !!this.message,
      initialization_error: this.initializationError ?? null,
      native_services: { agents: !!this.ctx.agents?.create, goals: !!this.goals(),
        goal_api: this.goals() ? Object.getOwnPropertyNames(Object.getPrototypeOf(this.goals())).filter(k => !k.startsWith('_')).slice(0, 30) : [] },
      model: this.model, missing_tools: missing, max_iterations: 3, max_duration_ms: 480000,
      verification_kind: 'SANDBOX_PROTECTED_UNITTEST', canonical_cycle_execution: false }
  }
  goals() { try { return this.ctx.get('goals') } catch { return null } }
  persist(job) {
    mkdirSync(this.root, { recursive: true })
    const path = join(this.root, job.loop_id + '.json')
    const { command, checking, finishing, ...publicJob } = job
    writeFileSync(path + '.tmp', JSON.stringify({ ...publicJob, command }), { mode: 0o600 })
    renameSync(path + '.tmp', path)
  }
  read(id, scope) {
    if (!UUID.test(id) || !/^[a-f0-9]{64}$/.test(scope)) fail('LOOP_NOT_FOUND')
    let job = this.jobs.get(id)
    if (!job) {
      try { job = JSON.parse(readFileSync(join(this.root, id + '.json'), 'utf8')) }
      catch { fail('LOOP_NOT_FOUND') }
      if (['RESERVED', 'RUNNING'].includes(job.state)) {
        // No native resume, create replay, or guess that idle means completed.
        job.state = 'UNCONFIRMED'; job.error_code = 'LOOP_INTERRUPTED_REVIEW_REQUIRED'
      }
    }
    if (job.scope_id !== scope || job.loop_id !== id) fail('LOOP_NOT_FOUND')
    const { command, checking, finishing, ...result } = job
    return structuredClone(result)
  }
  begin(raw) {
    const command = validateLoop(raw)
    try {
      const old = this.read(command.loop_id, command.scope_id)
      if (old.request_digest !== commandDigest(command)) fail('LOOP_ID_CONFLICT')
      return old
    } catch (e) { if (e.message !== 'LOOP_NOT_FOUND') throw e }
    // Do not overwrite a receipt from a different scope, including after restart.
    try { readFileSync(join(this.root, command.loop_id + '.json')); fail('LOOP_ID_CONFLICT') }
    catch (e) { if (e.code !== 'ENOENT') throw e }
    if (!this.capabilities().ready) fail('LOOP_RUNTIME_UNAVAILABLE')
    if ([...this.jobs.values()].some(j => ['RESERVED','RUNNING'].includes(j.state))) fail('LOOP_ALREADY_ACTIVE')
    mkdirSync(this.root, { recursive: true })
    if (readdirSync(this.root).filter(n => n.endsWith('.json')).length >= 100) fail('LOOP_CAPACITY')
    const job = { loop_id: command.loop_id, scope_id: command.scope_id, request_digest: commandDigest(command),
      base_commit: command.base_commit, goal: command.goal, state: 'RESERVED', created_at: new Date().toISOString(),
      model: this.model, iterations: [], files: {}, changed_paths: [], max_iterations: command.max_iterations,
      canonical_cycle_execution: false, verification_kind: 'SANDBOX_PROTECTED_UNITTEST',
      release_status: 'REVIEW_REQUIRED', command }
    this.persist(job); this.jobs.set(job.loop_id, job)
    void this.run(job).catch(() => {})
    return this.read(job.loop_id, job.scope_id)
  }
  async call(name, args, agent, signal) {
    signal ??= this.controllers.values().next().value?.signal ?? AbortSignal.timeout(180000)
    const result = await this.ctx.tools.get(name).execute(args, { agent, signal, callId: randomUUID() })
    if (typeof result === 'string') { try { return JSON.parse(result) } catch { return { text: result } } }
    return result
  }
  async contract(job, patch) {
    const value = await this.call('taskloop_update_task', { n: '1', ...patch }, this.handles.get(job.loop_id)?.agent)
    if (value?.ok !== true || value.task?.status !== patch.status) fail('LOOP_CONTRACT_UPDATE_UNCONFIRMED')
    job.contract = { ...job.contract, n: '1', status: value.task.status }
    return value
  }
  async verify(job, files, n) {
    const session = `pokedev-loop-${job.loop_id}-${n}`
    job.sandbox_id = session; this.persist(job)
    return this.verifyFiles(job.command, files, session)
  }
  async verifyFiles(command, files, session, ttl = 900, profile = {}) {
    const phase = profile.onPhase ?? (() => {})
    phase('SANDBOX_CREATE')
    const made = await this.call('sandbox_create', { session_id: session, project_path: session,
      image: profile.image ?? 'python:3.11-slim', cpu: '1', memory: profile.memory ?? '512Mi', ttl })
    if ((made.sessionId ?? made.session_id) !== session) fail('LOOP_SANDBOX_CREATE_UNCONFIRMED')
    phase('SANDBOX_READY')
    for (let index = 0; index < 25; index++) {
      const state = await this.call('sandbox_status', { session_id: session })
      if (state.status === 'RUNNING' || state.runnerConnected === true) break
      await delay(800)
    }
    phase('WRITE_INPUTS')
    if (profile.preparePython) {
      phase('SETUP_RUNTIME')
      const setup = await this.call('sandbox_shell', { session_id: session, timeout: 90,
        command: 'command -v python3 >/dev/null 2>&1 || apk add --no-cache python3' })
      if (setup.exitCode !== 0) fail('LOOP_RUNTIME_SETUP_FAILED')
    }
    const protectedHashes = Object.fromEntries(Object.entries(command.files)
      .filter(([p]) => !command.writable_paths.includes(p)).map(([p, text]) => [p, hash(text)]))
    const snapshot = { ...command.files, ...files,
      'pokedev-checks.json': JSON.stringify({ protected: protectedHashes, checks: command.checks }),
      'pokedev-verify.py': readFileSync(new URL('./loop-verifier.py', import.meta.url), 'utf8') }
    for (const [filepath, contents] of Object.entries(snapshot))
      await this.call('sandbox_write_file', { session_id: session, filepath, contents })
    phase('RUN_TESTS')
    const executed = await this.call('sandbox_shell', { session_id: session, timeout: 150,
      command: (profile.preparePython ? 'python3' : 'python') + ' -I pokedev-verify.py' })
    const line = String(executed.stdout ?? '').split(/\r?\n/).findLast(s => s.startsWith('POKEDEV_LOOP_CHECK:'))
    if (executed.exitCode !== 0 || !line) fail('LOOP_CHECK_RESULT_UNCONFIRMED')
    const result = JSON.parse(line.slice('POKEDEV_LOOP_CHECK:'.length))
    if (typeof result.protected_intact !== 'boolean' || !Array.isArray(result.checks)
        || result.checks.length !== command.checks.length
        || result.checks.some((r, i) => r.check_id !== command.checks[i].check_id || !Number.isInteger(r.exit_code))) fail('LOOP_CHECK_RESULT_INVALID')
    return { ...result, passed: result.protected_intact && result.checks.every(c => c.exit_code === 0), sandbox_id: session }
  }
  async propose(args, exec) {
    const job = [...this.jobs.values()].find(j => this.handles.get(j.loop_id)?.agent === exec.agent)
    if (!job || job.state !== 'RUNNING' || job.checking) fail('LOOP_TOOL_DENIED')
    if (job.iterations.length >= job.max_iterations) fail('LOOP_ITERATION_LIMIT')
    if (!args || Object.keys(args).join(',') !== 'files' || !args.files || Array.isArray(args.files)
        || !Object.keys(args.files).length || Object.entries(args.files).some(([p, text]) =>
          !job.command.writable_paths.includes(p) || typeof text !== 'string' || Buffer.byteLength(text) > 65536)) fail('LOOP_WRITE_SCOPE_DENIED')
    job.checking = true
    const iteration = { number: job.iterations.length + 1, state: 'CHECKING', started_at: new Date().toISOString() }
    job.iterations.push(iteration)
    job.files = { ...job.files, ...args.files }; this.persist(job)
    try {
      const result = await this.verify(job, job.files, iteration.number)
      job.changed_paths = Object.keys(job.files).filter(p => job.files[p] !== job.command.files[p])
      Object.assign(iteration, result, { state: result.passed ? 'PASSED' : 'FAILED' })
      this.persist(job)
      if (result.passed && job.changed_paths.length) {
        await this.contract(job, { status: 'DONE', comment: 'Protected sandbox checks passed; source changed. Human review is still required.' })
        job.finishing = true
      } else if (job.iterations.length >= job.max_iterations) {
        job.state = 'FAILED'; job.error_code = result.passed ? 'LOOP_NO_SOURCE_CHANGE' : 'LOOP_BUDGET_EXHAUSTED'
        await this.contract(job, { status: 'BLOCKED' })
      }
      this.persist(job)
      return { ...result, changed_paths: job.changed_paths, remaining_iterations: job.max_iterations - job.iterations.length,
        instruction: job.finishing ? 'Task completed. Summarize the changes and stop.' : 'Fix only writable files using these actual findings.' }
    } finally { job.checking = false }
  }
  async run(job) {
    let timer, handle
    const controller = new AbortController()
    this.controllers.set(job.loop_id, controller)
    try {
      job.state = 'RUNNING'; job.phase = 'BASELINE'; this.persist(job)
      job.baseline = await this.verify(job, {}, 'baseline'); this.persist(job)
      job.phase = 'MEMORY'; this.persist(job)
      try {
        const health = await this.call('memory_health', {})
        const memory = new SessionMemoryClient(health.url, AbortSignal.timeout(60000))
        await memory.initialize()
        const session = 'pokedev-loop-' + job.loop_id
        const marker = 'PokeDevLoop' + job.loop_id.replaceAll('-', '')
        await memory.call('remember', { session_id: session, self_improvement: false,
          data: marker + ' baseline=' + job.base_commit + '; goal=' + job.goal.slice(0, 2000) })
        const recalled = await memory.call('recall', { session_id: session, query: marker, top_k: 1 })
        const text = (recalled.content ?? []).map(c => c.text ?? '').join('\n')
        job.memory = { mode: 'SESSION_CACHE', session_id: session, recalled: text.includes('[session] ' + marker) }
      } catch { job.memory = { mode: 'SESSION_CACHE', recalled: false, error_code: 'MEMORY_CONTEXT_UNAVAILABLE' } }
      this.persist(job)
      const workspace = join(this.workspaces, job.loop_id)
      mkdirSync(workspace, { recursive: true })
      const trusted = this.ctx.tools.get(PROPOSE_TOOL)
      job.phase = 'NATIVE_CREATE'; this.persist(job)
      handle = await this.ctx.agents.create({ sessionId: job.loop_id,
        agentOptions: { provider: this.model.provider, model: this.model.model },
        meta: { cwd: workspace, agentPreset: 'standard' },
        setup: (ctx, agent) => {
          if (!['restrict','guard','presentAs','schemas'].every(k => typeof ctx.tools?.[k] === 'function')) fail('LOOP_TOOL_SCOPE_UNAVAILABLE')
          ctx.tools.presentAs('native'); ctx.tools.restrict({ allow: [PROPOSE_TOOL] })
          ctx.tools.guard(e => e.agent === agent && e.name === PROPOSE_TOOL && ctx.tools.get(e.name, agent) === trusted ? undefined : 'LOOP_TOOL_DENIED')
          return { commit() {
            const names = ctx.tools.schemas(agent).map(x => x.name)
            if (names.length !== 1 || names[0] !== PROPOSE_TOOL) fail('LOOP_TOOL_SCOPE_UNAVAILABLE')
          } }
        } })
      this.handles.set(job.loop_id, handle)
      job.session_id = handle.agent.session.id
      job.phase = 'CONTRACT'; this.persist(job)
      const created = await this.call('taskloop_create_task', { n: '1', name: job.goal.slice(0, 180), model: this.model.model,
        brief: 'taskloop/brief.md', dir: workspace, report: 'taskloop/report.md',
        ctx: 'PokeDev pinned source and protected checks. Review required; no commit or release.', status: 'PENDING' }, handle.agent)
      if (created?.ok !== true || created.task?.status !== 'PENDING') fail('LOOP_CONTRACT_CREATE_UNCONFIRMED')
      await this.contract(job, { status: 'IN_PROGRESS' })
      job.contract = { n: '1', workspace, status: 'IN_PROGRESS' }
      job.goal_state = this.goals()?.get(handle.agent) ?? null
      if (!job.goal_state || typeof this.goals().edit !== 'function') fail('LOOP_GOAL_BUDGET_UNAVAILABLE')
      this.goals().edit(handle.agent, { id: job.goal_state.id, revision: job.goal_state.revision }, { maxGoalRounds: job.max_iterations })
      job.goal_state = this.goals().get(handle.agent)
      this.persist(job)
      timer = setTimeout(() => {
        if (job.state === 'RUNNING') {
          job.state = 'FAILED'; job.error_code = 'LOOP_DURATION_LIMIT'; this.persist(job)
          void this.contract(job, { status: 'BLOCKED' }).catch(() => {})
          handle.agent.cancel({ kind: 'user' })
          controller.abort()
        }
      }, 480000)
      timer.unref?.()
      const prompt = 'Implement this PokeDev task using ONLY pokedev_loop_propose. Each call submits full replacement contents for writable files and runs real protected tests. '
        + 'Do not invoke shell, Git, network, other agents, or alter tests. Submit files before claiming completion. Fix failures until checks pass, at most '
        + job.max_iterations + ' proposals. TaskLoop and native Goal control continuation. Return a short Vietnamese summary.\n'
        + JSON.stringify({ goal: job.goal, writable_paths: job.command.writable_paths, files: job.command.files,
          baseline_findings: job.baseline, base_commit: job.base_commit })
      handle.agent.followup(this.message({ content: [{ type: 'text', text: prompt }], source: { kind: 'plugin', plugin: 'vai-pokedev-services' } }))
      job.phase = 'IMPLEMENT'; this.persist(job)
      // Observe native Goal/TaskLoop; never finalize solely because a turn is idle.
      for (let n = 0; n < 245 && job.state === 'RUNNING' && !job.finishing; n++) {
        await delay(2000)
        job.goal_state = this.goals()?.get(handle.agent) ?? null
        if (job.goal_state && ['blocked','paused','complete'].includes(job.goal_state.phase) && !job.checking && !job.finishing) {
          job.state = 'FAILED'; job.error_code = 'LOOP_STOPPED_WITHOUT_VERIFIED_CHANGE'
        }
        this.persist(job)
      }
      if (job.state === 'RUNNING' && !job.finishing) { job.state = 'FAILED'; job.error_code = 'LOOP_DURATION_LIMIT' }
      await handle.agent.whenIdle()
      job.goal_state = this.goals()?.get(handle.agent) ?? null
      const finalContract = await this.call('taskloop_get_task', { n: '1' }, handle.agent)
      if (finalContract?.ok !== true) fail('LOOP_CONTRACT_READ_UNCONFIRMED')
      job.contract = { ...job.contract, status: finalContract.task.status }
      const events = handle.agent.session.snapshotEvents()
      const replies = events.filter(e => e.type === 'assistant/message')
      job.usage = { input_tokens: null, output_tokens: null, cost: null }
      if (replies.length && replies.every(e => Number.isSafeInteger(e.data?.usage?.inputTokens) && Number.isSafeInteger(e.data?.usage?.outputTokens)))
        job.usage = { input_tokens: 0, output_tokens: 0, cost: null }
      for (const event of replies) {
        if (event.data?.message?.source?.provider !== this.model.provider || event.data?.message?.source?.model !== this.model.model) fail('LOOP_NATIVE_MODEL_MISMATCH')
        if (job.usage.input_tokens !== null) job.usage.input_tokens += event.data.usage.inputTokens
        if (job.usage.output_tokens !== null) job.usage.output_tokens += event.data.usage.outputTokens
      }
      job.native_turns = events.filter(e => e.type === 'turn/end').length
      job.summary = replies.at(-1)?.data?.message?.content?.filter(c => c.type === 'text').map(c => c.text).join('\n').slice(0, 4000) ?? ''
      if (job.finishing && job.goal_state?.phase === 'complete' && job.contract.status === 'DONE') job.state = 'SUCCEEDED'
      else if (job.finishing) fail('LOOP_GOAL_COMPLETION_UNCONFIRMED')
    } catch (error) {
      job.state = 'FAILED'; job.error_code = /^LOOP_[A-Z_]+$/.test(error.message) ? error.message : 'LOOP_EXECUTION_FAILED'
      job.failure = { phase: job.phase, kind: error?.name, code: error?.code,
        message: String(error?.message ?? '').replace(/(Bearer\s+)[A-Za-z0-9._~+\/-]+=*/gi, '$1[redacted]')
          .replace(/([?&](?:token|password|api_key)=)[^&\s]+/gi, '$1[redacted]').replace(/:\/\/[^/@\s]+:[^/@\s]+@/g, '://[redacted]@').slice(0, 800) }
      if (handle) { await this.contract(job, { status: 'BLOCKED' }).catch(() => {}); handle.agent.cancel({ kind: 'user' }) }
    } finally {
      clearTimeout(timer)
      job.completed_at = new Date().toISOString(); this.persist(job)
      if (handle) await handle.dispose().catch(() => {})
      this.handles.delete(job.loop_id)
      this.controllers.delete(job.loop_id)
    }
  }
}

export function registerProposalTool(ctx, loops) {
  ctx.tools.register({ name: PROPOSE_TOOL,
    description: 'Submit complete replacement Python source for this owned PokeDev task. Runs fixed protected checks in a fresh Sandbox and returns real findings. No approval or publication.',
    parameters: { type: 'object', properties: { files: { type: 'object', additionalProperties: { type: 'string' } } }, required: ['files'], additionalProperties: false },
    async execute(args, exec) { return loops.propose(args, exec) },
    output: { schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: value?.passed ? 'Protected checks passed.' : 'Protected checks returned findings.' }] } })
}

export function loopHandler(loops, authenticate) {
  return async (request, response) => {
    const send = (status, result) => { response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' }); response.end(JSON.stringify(result)) }
    try {
      const rejection = authenticate?.(request) ?? (authenticate ? undefined : 503)
      if (rejection !== undefined) return send(rejection, { error_code: 'LOOP_UNAUTHENTICATED' })
      const url = new URL(request.url, 'http://platform.local')
      if (request.method === 'GET' && url.pathname === LOOP_ROOT + '/capabilities') return send(200, loops.capabilities())
      const match = new RegExp('^' + LOOP_ROOT + '/([a-f0-9-]{36})$').exec(url.pathname)
      if (request.method === 'GET' && match) return send(200, loops.read(match[1], url.searchParams.get('scope_id')))
      if (request.method === 'POST' && url.pathname === LOOP_ROOT) {
        const chunks = []; let size = 0
        for await (const chunk of request) { size += chunk.length; if (size > 150000) fail('LOOP_REQUEST_TOO_LARGE'); chunks.push(Buffer.from(chunk)) }
        return send(202, loops.begin(JSON.parse(Buffer.concat(chunks).toString('utf8'))))
      }
      return send(404, { error_code: 'LOOP_NOT_FOUND' })
    } catch (e) { return send(e.message === 'LOOP_NOT_FOUND' ? 404 : 409, { error_code: /^LOOP_[A-Z_]+$/.test(e.message) ? e.message : 'LOOP_REQUEST_INVALID' }) }
  }
}
