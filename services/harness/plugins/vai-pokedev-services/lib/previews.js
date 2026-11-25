import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

export const PREVIEW_ROOT = '/api/v1/pokedev-services/previews'
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/
const scopeOK = s => /^[a-f0-9]{64}$/.test(s ?? '')
const sha = s => createHash('sha256').update(s).digest('hex')
const fail = code => { throw Error(code) }

export function validatePreviewRequest(c) {
  if (!c || Object.keys(c).sort().join(',') !== 'body,method,path,scope_id' || !scopeOK(c.scope_id)
      || typeof c.body !== 'string' || Buffer.byteLength(c.body) > 4096) fail('PREVIEW_HTTP_INVALID')
  const allowed = c.method === 'GET' && (c.path === '/' || /^\/api\/tasks(?:\?status=(?:all|open|done))?$/.test(c.path))
    || c.method === 'POST' && c.path === '/api/tasks'
    || ['PATCH','DELETE'].includes(c.method) && /^\/api\/tasks\/[0-9]{1,12}$/.test(c.path)
  if (!allowed || ['GET','DELETE'].includes(c.method) && c.body) fail('PREVIEW_HTTP_INVALID')
  return c
}

export function previewURL(raw) {
  if (typeof raw !== 'string') fail('PREVIEW_ENDPOINT_UNAVAILABLE')
  const url = new URL(raw.includes('://') ? raw : 'http://' + raw)
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    fail('PREVIEW_ENDPOINT_INVALID')
  return url.href
}

export class ProductPreviews {
  constructor(loops, { dataDir, endpoint }) { this.loops = loops; this.root = dataDir; this.endpoint = endpoint; this.jobs = new Map() }
  persist(job) {
    mkdirSync(this.root, { recursive: true })
    const path = join(this.root, job.preview_id + '.json')
    writeFileSync(path + '.tmp', JSON.stringify(job), { mode: 0o600 }); renameSync(path + '.tmp', path)
  }
  read(id, scope) {
    if (!UUID.test(id ?? '') || !scopeOK(scope)) fail('PREVIEW_NOT_FOUND')
    let job = this.jobs.get(id)
    if (!job) {
      try { job = JSON.parse(readFileSync(join(this.root, id + '.json'), 'utf8')) } catch { fail('PREVIEW_NOT_FOUND') }
      if (['VERIFYING', 'DEPLOYING'].includes(job.state)) { job.state = 'UNCONFIRMED'; job.error_code = 'PREVIEW_INTERRUPTED' }
    }
    if (job.scope_id !== scope || job.preview_id !== id) fail('PREVIEW_NOT_FOUND')
    return structuredClone(job)
  }
  begin(c) {
    if (!c || Object.keys(c).sort().join(',') !== 'loop_id,preview_id,scope_id' || !UUID.test(c.preview_id ?? '')
        || !UUID.test(c.loop_id ?? '') || !scopeOK(c.scope_id)) fail('PREVIEW_COMMAND_INVALID')
    try {
      const old = this.read(c.preview_id, c.scope_id)
      if (old.loop_id !== c.loop_id) fail('PREVIEW_ID_CONFLICT')
      return old
    } catch (e) { if (e.message !== 'PREVIEW_NOT_FOUND') throw e }
    try { readFileSync(join(this.root, c.preview_id + '.json')); fail('PREVIEW_ID_CONFLICT') }
    catch (e) { if (e.code !== 'ENOENT') throw e }
    const native = this.loops.read(c.loop_id, c.scope_id)
    if (native.state !== 'SUCCEEDED' || !native.changed_paths?.includes('app.py') || !native.files?.['app.py']) fail('PREVIEW_CANDIDATE_REQUIRED')
    mkdirSync(this.root, { recursive: true })
    if ([...this.jobs.values()].some(j => ['VERIFYING','DEPLOYING'].includes(j.state)) || readdirSync(this.root).length > 100) fail('PREVIEW_CAPACITY')
    const job = { ...c, state: 'VERIFYING', source_sha256: sha(native.files['app.py']), created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 3600000).toISOString(), sandbox_id: 'pokedev-preview-' + c.preview_id,
      verification_kind: 'SANDBOX_PROTECTED_UNITTEST', attested: false, port: 8088 }
    this.jobs.set(c.preview_id, job); this.persist(job)
    void this.verify(job).catch(() => {})
    return this.read(c.preview_id, c.scope_id)
  }
  async verify(job) {
    try {
      const native = this.loops.read(job.loop_id, job.scope_id)
      // Durable command is kept server-side, never accepted from a preview caller.
      const stored = JSON.parse(readFileSync(join(this.loops.root, job.loop_id + '.json'), 'utf8'))
      job.image = 'adlc-test-worker:local'
      job.tests = await this.loops.verifyFiles(stored.command, native.files, job.sandbox_id, 3600,
        { image:job.image, memory:'1Gi', preparePython:true, onPhase:phase => { job.phase = phase; this.persist(job) } })
      if (!job.tests.passed || !job.tests.protected_intact) fail('PREVIEW_TESTS_FAILED')
      job.state = 'VERIFIED'; this.persist(job)
    } catch (e) {
      job.state = 'FAILED'; job.error_code = /^PREVIEW_[A-Z_]+$/.test(e.message) ? e.message : 'PREVIEW_VERIFY_FAILED'
      job.failure_kind = /timeout|abort/i.test(e.name + ' ' + e.message) ? 'TIMEOUT'
        : /unreachable|fetch failed|ECONN/i.test(e.message) ? 'BROKER_UNAVAILABLE'
          : /broker HTTP (\d+)/.exec(e.message)?.[0] ?? e.name
      if (/^LOOP_[A-Z_]+$/.test(e.message)) job.failure_code = e.message
      this.persist(job)
    }
  }
  deploy(id, scope) {
    const job = this.read(id, scope)
    if (job.state === 'LIVE' || job.deploy_dispatched) return job
    if (job.state !== 'VERIFIED' || !this.jobs.has(id)) fail('PREVIEW_NOT_VERIFIED')
    const live = this.jobs.get(id)
    live.state = 'DEPLOYING'; live.deploy_dispatched = true; this.persist(live)
    void this.start(live).catch(() => {})
    return this.read(id, scope)
  }
  async start(job) {
    try {
      const binding = { preview_id: job.preview_id, source_sha256: job.source_sha256 }
      for (const [filepath, contents] of Object.entries({ 'pokedev-preview-binding.json': JSON.stringify(binding),
        'pokedev-preview-http.py': readFileSync(new URL('./preview-http.py', import.meta.url), 'utf8'),
        'pokedev-preview-start.py': readFileSync(new URL('./preview-start.py', import.meta.url), 'utf8') }))
        await this.loops.call('sandbox_write_file', { session_id: job.sandbox_id, filepath, contents })
      const execution = await this.loops.call('sandbox_shell', { session_id: job.sandbox_id, timeout: 60, command: 'python3 pokedev-preview-start.py' })
      const line = String(execution.stdout ?? '').split(/\r?\n/).findLast(s => s.startsWith('POKEDEV_PREVIEW_START:'))
      if (execution.exitCode !== 0 || !line) fail('PREVIEW_START_UNCONFIRMED')
      const report = JSON.parse(line.slice('POKEDEV_PREVIEW_START:'.length))
      if (report.preview_id !== job.preview_id || report.source_sha256 !== job.source_sha256 || !report.passed
          || report.verification_kind !== 'LIVE_HTTP_SMOKE' || report.attested !== false || report.checks?.length !== 5
          || report.checks.some(c => c.passed !== true)) fail('PREVIEW_HTTP_FAILED')
      job.http = report
      // Broker endpoints may be host-local Docker ports. The scoped relay reaches
      // the running application without publishing an unusable loopback URL.
      job.access_mode = 'POKEDEV_RELAY'; job.state = 'LIVE'; this.persist(job)
    } catch (e) { job.state = 'UNCONFIRMED'; job.error_code = /^PREVIEW_[A-Z_]+$/.test(e.message) ? e.message : 'PREVIEW_DEPLOY_UNCONFIRMED'; this.persist(job) }
  }
  async proxy(id, command) {
    const c = validatePreviewRequest(command), job = this.read(id, c.scope_id)
    if (job.state !== 'LIVE' || Date.parse(job.expires_at) <= Date.now()) fail('PREVIEW_NOT_LIVE')
    const encoded = Buffer.from(JSON.stringify({ method:c.method,path:c.path,body:c.body })).toString('base64')
    const executed = await this.loops.call('sandbox_shell', { session_id:job.sandbox_id,timeout:15,
      command:'python3 pokedev-preview-http.py ' + encoded })
    const line = String(executed.stdout ?? '').split(/\r?\n/).findLast(s => s.startsWith('POKEDEV_PREVIEW_HTTP:'))
    if (executed.exitCode !== 0 || !line) fail('PREVIEW_HTTP_UNAVAILABLE')
    const result = JSON.parse(line.slice('POKEDEV_PREVIEW_HTTP:'.length))
    if (!Number.isInteger(result.status) || result.status < 200 || result.status > 599
        || !['text/html; charset=utf-8','application/json; charset=utf-8'].includes(result.content_type)
        || typeof result.body_base64 !== 'string' || result.body_base64.length > 180000) fail('PREVIEW_HTTP_INVALID')
    return result
  }
}

export function previewHandler(previews, authenticate) {
  return async (req, res) => {
    const send = (n, body) => { res.writeHead(n, { 'content-type':'application/json', 'cache-control':'no-store' }); res.end(JSON.stringify(body)) }
    try {
      const rejection = typeof authenticate === 'function' ? authenticate(req) : 503
      if (rejection !== undefined) return send(rejection, { error_code:'PREVIEW_ACCESS_DENIED' })
      const u = new URL(req.url, 'http://platform.local')
      if (req.method === 'GET' && u.pathname === PREVIEW_ROOT + '/capabilities')
        return send(200, { version:'0.1.0', release:'0.4.1', ready:true, relay:true,
          profile:'PYTHON_TASKBOARD', runner_image:'adlc-test-worker:local', python:'python3', ttl_seconds:3600 })
      const match = new RegExp('^'+PREVIEW_ROOT+'/([a-f0-9-]{36})(/(?:deploy|http))?$').exec(u.pathname)
      if (req.method === 'GET' && match && !match[2]) return send(200, previews.read(match[1], u.searchParams.get('scope_id')))
      if (req.method === 'POST' && (u.pathname === PREVIEW_ROOT || match?.[2])) {
        const chunks = []; let size = 0
        for await (const chunk of req) { size += chunk.length; if (size > 12000) fail('PREVIEW_COMMAND_INVALID'); chunks.push(Buffer.from(chunk)) }
        const c = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        if (match) {
          if (match[2] === '/http') return send(200, await previews.proxy(match[1], c))
          if (Object.keys(c).join(',') !== 'scope_id') fail('PREVIEW_COMMAND_INVALID')
          return send(202, previews.deploy(match[1], c.scope_id))
        }
        return send(202, previews.begin(c))
      }
      return send(404, { error_code:'PREVIEW_NOT_FOUND' })
    } catch (e) { return send(e.message === 'PREVIEW_NOT_FOUND' ? 404 : 409, { error_code:/^PREVIEW_[A-Z_]+$/.test(e.message) ? e.message : 'PREVIEW_REQUEST_INVALID' }) }
  }
}
