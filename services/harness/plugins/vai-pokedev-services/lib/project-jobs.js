import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs'
import { join } from 'node:path'

export const PROJECT_ROOT = '/api/v1/pokedev-services/projects'
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/
const hex = /^[a-f0-9]{64}$/
const sha = value => createHash('sha256').update(value).digest('hex')
const fail = code => { throw new Error(code) }
const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
const safePath = p => typeof p === 'string' && p.length < 301 && !/^[\/]|[\\:\x00-\x1f]/.test(p) && p.split('/').every(x => x && !['.', '..', '.git'].includes(x) && !x.startsWith('.env'))

export function validateProjectJob(c) {
  if (!uuid.test(c.job_id ?? '') || !hex.test(c.scope_id ?? '') || !hex.test(c.source_sha256 ?? '') || !hex.test(c.plan_digest ?? '')
      || typeof c.archive_base64 !== 'string' || c.archive_base64.length > 80000000) fail('PROJECT_JOB_INVALID')
  if (sha(Buffer.from(c.archive_base64, 'base64')) !== c.source_sha256) fail('PROJECT_SOURCE_HASH_MISMATCH')
  if (!Array.isArray(c.commands) || !c.commands.length || c.commands.length > 8) fail('PROJECT_COMMANDS_REQUIRED')
  for (const command of c.commands) {
    if (!Array.isArray(command.argv) || !command.argv.length || command.argv.length > 40 || command.argv.some(x => typeof x !== 'string' || x.length > 500 || x.includes('\0'))) fail('PROJECT_COMMAND_INVALID')
  }
  if (!Array.isArray(c.protected_paths) || c.protected_paths.length > 2000 || c.protected_paths.some(p => !safePath(p))) fail('PROJECT_PROTECTED_PATHS_INVALID')
  if (c.preview && (typeof c.preview !== 'object' || !!c.preview.path === !!c.preview.argv || (c.preview.path && c.preview.path !== '.' && !safePath(c.preview.path)) || (c.preview.argv && (!Array.isArray(c.preview.argv) || !c.preview.argv.length || c.preview.argv.length > 40 || c.preview.argv.some(x => typeof x !== 'string' || !x || x.length > 500 || x.includes('\0')))))) fail('PROJECT_PREVIEW_INVALID')
  if (!Array.isArray(c.browser_checks ?? []) || (c.browser_checks ?? []).length > 15) fail('PROJECT_BROWSER_CHECK_LIMIT')
  for (const check of c.browser_checks ?? []) {
    if (typeof check.label !== 'string' || !check.label || !Array.isArray(check.steps) || !check.steps.length || check.steps.length > 30) fail('PROJECT_BROWSER_CHECK_INVALID')
    for (const step of check.steps) {
      const keys = { goto: ['path'], text: ['text'], visible: ['selector'], fill: ['selector', 'value'], click: ['selector'] }[step.action]
      if (!keys || keys.some(k => typeof step[k] !== 'string' || step[k].length > 2000) || (step.action === 'goto' && (!step.path.startsWith('/') || step.path.startsWith('//') || step.path.includes('\\')))) fail('PROJECT_BROWSER_CHECK_INVALID')
    }
  }
  return c
}

export class ProjectJobs {
  constructor(checks, root) { this.checks = checks; this.root = root; this.jobs = new Map() }
  persist(job) { mkdirSync(this.root, { recursive: true }); const path = join(this.root, job.job_id + '.json'); writeFileSync(path + '.tmp', JSON.stringify(job), { mode: 0o600 }); renameSync(path + '.tmp', path) }
  read(id, scope) {
    if (!uuid.test(id ?? '') || !hex.test(scope ?? '')) fail('PROJECT_JOB_NOT_FOUND')
    let job = this.jobs.get(id)
    if (!job) {
      try { job = JSON.parse(readFileSync(join(this.root, id + '.json'), 'utf8')) } catch { fail('PROJECT_JOB_NOT_FOUND') }
      if (job.state === 'RUNNING') job = { ...job, state: 'UNCONFIRMED', error_code: 'PROJECT_WORKER_INTERRUPTED' }
    }
    if (job.scope_id !== scope) fail('PROJECT_JOB_NOT_FOUND')
    return structuredClone(job)
  }
  async call(name, args) {
    const tool = this.checks.tool(name)
    if (!tool?.execute) fail('PROJECT_SANDBOX_TOOL_UNAVAILABLE')
    let result = await tool.execute(args, { signal: AbortSignal.timeout(240000), callId: randomUUID() })
    if (typeof result === 'string') result = JSON.parse(result)
    return result
  }
  begin(input) {
    const c = validateProjectJob(input)
    const binding = sha(JSON.stringify(c))
    try { const old = this.read(c.job_id, c.scope_id); if (old.request_digest !== binding) fail('PROJECT_JOB_ID_CONFLICT'); return old } catch (e) { if (e.message !== 'PROJECT_JOB_NOT_FOUND') throw e }
    // IDs are global and cannot be rebound under another scope.
    try { readFileSync(join(this.root, c.job_id + '.json')); fail('PROJECT_JOB_ID_CONFLICT') } catch (e) { if (e.code !== 'ENOENT') throw e }
    const job = { job_id: c.job_id, scope_id: c.scope_id, plan_digest: c.plan_digest, source_sha256: c.source_sha256, request_digest: binding,
      state: 'RUNNING', created_at: new Date().toISOString(), expires_at: Date.now() / 1000 + 7200, sandbox_id: 'pokedev-project-' + c.job_id, checks: [], browser_checks: [] }
    this.jobs.set(job.job_id, job); this.persist(job)
    void this.execute(job, c).catch(() => {})
    return this.read(job.job_id, job.scope_id)
  }
  async execute(job, c) {
    try {
      const health = await this.call('testforge_health', {})
      if (!health.sandbox_image) fail('PROJECT_TESTFORGE_IMAGE_UNAVAILABLE')
      const created = await this.call('sandbox_create', { session_id: job.sandbox_id, project_path: job.sandbox_id, image: health.sandbox_image, cpu: '2', memory: '3Gi', ttl: 7200 })
      if ((created.sessionId ?? created.session_id) !== job.sandbox_id) fail('PROJECT_SANDBOX_CREATE_UNCONFIRMED')
      let ready = false
      for (let i = 0; i < 40; i++) { const status = await this.call('sandbox_status', { session_id: job.sandbox_id }); if (status.status === 'RUNNING' || status.runnerConnected) { ready = true; break } await pause(1000) }
      if (!ready) fail('PROJECT_SANDBOX_NOT_READY')
      const chunks = Math.ceil(c.archive_base64.length / 240000)
      for (let i = 0; i < chunks; i++) await this.call('sandbox_write_file', { session_id: job.sandbox_id, filepath: 'project-upload-' + i + '.txt', contents: c.archive_base64.slice(i * 240000, (i + 1) * 240000) })
      await this.call('sandbox_write_file', { session_id: job.sandbox_id, filepath: 'project-job.json', contents: JSON.stringify({ ...c, archive_base64: undefined, chunks }) })
      await this.call('sandbox_write_file', { session_id: job.sandbox_id, filepath: 'pokedev-project-runner.py', contents: readFileSync(new URL('./project-runner.py', import.meta.url), 'utf8') })
      await this.call('sandbox_write_file', { session_id: job.sandbox_id, filepath: 'pokedev-project-http.py', contents: readFileSync(new URL('./project-http.py', import.meta.url), 'utf8') })
      await this.call('sandbox_shell', { session_id: job.sandbox_id, timeout: 15, command: 'python -u pokedev-project-runner.py > pokedev-project-worker.log 2>&1 & echo POKEDEV_PROJECT_STARTED' })
      for (let i = 0; i < 900; i++) {
        const observed = await this.call('sandbox_shell', { session_id: job.sandbox_id, timeout: 15, command: `python -c "from pathlib import Path; p=Path('project-result.json'); print('POKEDEV_PROJECT_RESULT:'+ (p.read_text() if p.exists() else '{}'))"` })
        const line = String(observed.stdout ?? '').split(/\r?\n/).findLast(s => s.startsWith('POKEDEV_PROJECT_RESULT:'))
        if (!line) fail('PROJECT_RUNNER_RESPONSE_UNCONFIRMED')
        const result = JSON.parse(line.slice('POKEDEV_PROJECT_RESULT:'.length))
        if (result.job_id) {
          if (result.job_id !== c.job_id || result.scope_id !== c.scope_id || result.source_sha256 !== c.source_sha256 || result.plan_digest !== c.plan_digest) fail('PROJECT_RESULT_BINDING_MISMATCH')
          Object.assign(job, result); this.persist(job)
          if (['SUCCEEDED', 'FAILED'].includes(job.state)) return
        }
        await pause(2000)
      }
      fail('PROJECT_RUNNER_TIMEOUT')
    } catch (error) {
      job.state = 'FAILED'; job.error_code = /^PROJECT_[A-Z_]+$/.test(error.message) ? error.message : 'PROJECT_SANDBOX_OPERATION_FAILED'; this.persist(job)
    }
  }
  async http(id, c) {
    const job = this.read(id, c.scope_id)
    if (!job.preview_ready || Date.now() / 1000 >= job.expires_at || !/^\/(?!\/)/.test(c.path ?? '') || c.path.length > 1800 || /\.\.|\\|[\x00-\x1f]/.test(decodeURIComponent(c.path)) || !['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(c.method ?? 'GET') || (c.body_base64 ?? '').length > 1400000) fail('PROJECT_PREVIEW_REQUEST_INVALID')
    const name = 'preview-request-' + randomUUID() + '.json'
    await this.call('sandbox_write_file', { session_id: job.sandbox_id, filepath: name, contents: JSON.stringify({ path: c.path, method: c.method ?? 'GET', body: c.body_base64 ?? '', content_type: String(c.content_type ?? 'application/json').slice(0, 150) }) })
    const result = await this.call('sandbox_shell', { session_id: job.sandbox_id, timeout: 30, command: `python pokedev-project-http.py ${name}` })
    const line = String(result.stdout ?? '').split(/\r?\n/).findLast(s => s.startsWith('POKEDEV_PROJECT_HTTP:'))
    if (!line) fail('PROJECT_PREVIEW_RESPONSE_UNCONFIRMED')
    return JSON.parse(line.slice('POKEDEV_PROJECT_HTTP:'.length))
  }
}

export function projectHandler(service, authenticate) {
  return async (request, response) => {
    const send = (status, value) => { response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' }); response.end(JSON.stringify(value)) }
    try {
      const rejection = authenticate?.(request) ?? (authenticate ? undefined : 503)
      if (rejection !== undefined) return send(rejection, { error_code: 'PROJECT_UNAUTHENTICATED' })
      const url = new URL(request.url, 'http://platform.local')
      const match = new RegExp('^' + PROJECT_ROOT + '/jobs/([a-f0-9-]{36})(/http)?$').exec(url.pathname)
      if (request.method === 'GET' && url.pathname === PROJECT_ROOT + '/capabilities') return send(200, { version: '1.0', workloop: true, sandbox: ['sandbox_create', 'sandbox_status', 'sandbox_shell', 'sandbox_write_file'].every(name => !!service.checks.tool(name)?.execute), testforge: !!service.checks.tool('testforge_health')?.execute })
      if (request.method === 'GET' && match && !match[2]) return send(200, service.read(match[1], url.searchParams.get('scope_id')))
      if (request.method === 'POST' && (url.pathname === PROJECT_ROOT + '/jobs' || match?.[2] === '/http')) {
        const chunks = []; let size = 0
        for await (const part of request) { size += part.length; if (size > 82000000) fail('PROJECT_REQUEST_LIMIT'); chunks.push(Buffer.from(part)) }
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        return send(match ? 200 : 202, match ? await service.http(match[1], body) : service.begin(body))
      }
      return send(404, { error_code: 'PROJECT_ROUTE_NOT_FOUND' })
    } catch (error) { return send(error.message === 'PROJECT_JOB_NOT_FOUND' ? 404 : 409, { error_code: /^PROJECT_[A-Z_]+$/.test(error.message) ? error.message : 'PROJECT_OPERATION_FAILED' }) }
  }
}
