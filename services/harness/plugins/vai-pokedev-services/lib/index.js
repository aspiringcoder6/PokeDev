import { createHash, randomUUID } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync, renameSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { SessionMemoryClient, sessionContext } from './session-memory.js'
import { ProductLoops, registerProposalTool, loopHandler, LOOP_ROOT } from './product-loop.js'
import { ProductPreviews, previewHandler, PREVIEW_ROOT } from './previews.js'
import { TnqdBridge, tnqdHandler, TNQD_ROOT } from './tnqd.js'
import { ProjectJobs, projectHandler, PROJECT_ROOT } from './project-jobs.js'

export const name = 'vai-pokedev-services'
export const inject = ['tools', 'webServer', 'connection', 'agents', 'goals']
export const ROOT = '/api/v1/pokedev-services'
const TARGET = process.env.POKEDEV_TESTFORGE_TARGET_URL ?? 'http://host.docker.internal:7862/work'
const REQUIRED = {
  sandbox: ['sandbox_create', 'sandbox_status', 'sandbox_write_file', 'sandbox_read_file', 'sandbox_shell'],
  memory: ['memory_health', 'memory_remember', 'memory_context'],
  testforge: ['testforge_health', 'sandbox_create', 'sandbox_status', 'sandbox_write_file', 'sandbox_shell'],
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const timer = setTimeout(resolve, ms)
  signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('CHECK_TIMEOUT')) }, { once: true })
})

export function redact(value, depth = 0) {
  if (depth > 16) return '[nested data omitted]'
  if (typeof value === 'string') return value.slice(0, 24000)
    .replace(/(Bearer\s+)[A-Za-z0-9._~+/-]+=*/gi, '$1[redacted]')
    .replace(/([?&](?:token|password|api_key)=)[^&\s]+/gi, '$1[redacted]')
  if (Array.isArray(value)) return value.slice(0, 100).map(item => redact(item, depth + 1))
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 100).map(([key, item]) =>
    [key, /password|secret|authorization|credential|(?:^|_)token$|api.?key/i.test(key) ? '[redacted]' : redact(item, depth + 1)]))
  return value
}

export class ServiceChecks {
  constructor(ctx, config = {}) {
    this.ctx = ctx
    this.targets = new Set(config.allowedTargets ?? [TARGET])
    this.directory = config.dataDir
    this.jobs = new Map()
  }
  persist(job) {
    if (!this.directory) return
    mkdirSync(this.directory, { recursive: true })
    const path = join(this.directory, job.check_id + '.json')
    writeFileSync(path + '.tmp', JSON.stringify(this.public(job)), { mode: 0o600 })
    renameSync(path + '.tmp', path)
  }
  load(id) {
    if (!this.directory || !uuid.test(id)) return undefined
    try {
      const value = JSON.parse(readFileSync(join(this.directory, id + '.json'), 'utf8'))
      if (value.check_id !== id || !Object.hasOwn(REQUIRED, value.service)) return undefined
      return { ...value, controller: new AbortController() }
    } catch (error) { if (error?.code === 'ENOENT') return undefined; throw new Error('CHECK_RECEIPT_STORE_UNAVAILABLE') }
  }
  tool(name) { try { return this.ctx.tools.get(name) } catch { return undefined } }
  capabilities() {
    return { version: '0.1.0', no_agent_created: true, services: Object.fromEntries(Object.entries(REQUIRED).map(([service, names]) =>
      [service, { available: names.every(tool => typeof this.tool(tool)?.execute === 'function'),
        missing_tools: names.filter(tool => typeof this.tool(tool)?.execute !== 'function') }])), allowed_targets: [...this.targets] }
  }
  async call(job, toolName, args) {
    const tool = this.tool(toolName)
    if (!tool?.execute) throw new Error('TOOL_NOT_AVAILABLE:' + toolName)
    const start = Date.now()
    let value
    try { value = await tool.execute(args, { signal: job.controller.signal, callId: randomUUID() }) }
    catch (error) {
      job.steps.push({ tool: toolName, duration_ms: Date.now() - start, result: { error: redact(String(error?.message ?? 'TOOL_FAILED')) } })
      throw error
    }
    let parsed = value
    if (typeof value === 'string') { try { parsed = JSON.parse(value) } catch { parsed = { text: value } } }
    const safe = redact(parsed)
    job.steps.push({ tool: toolName, duration_ms: Date.now() - start, result: safe })
    job.updated_at = new Date().toISOString()
    this.persist(job)
    return parsed
  }
  begin(command, observeOnly = false, knownJob) {
    if (!command || Object.keys(command).some(key => !['check_id', 'service', 'scope_id', 'target_url'].includes(key))
        || !uuid.test(command.check_id ?? '') || !/^[a-f0-9]{32,64}$/.test(command.scope_id ?? '')
        || !Object.hasOwn(REQUIRED, command.service)) throw new Error('CHECK_ARGUMENTS_INVALID')
    if (command.service === 'testforge' && !this.targets.has(command.target_url ?? TARGET)) throw new Error('TARGET_NOT_ALLOWED')
    const digest = createHash('sha256').update(JSON.stringify([command.service, command.scope_id, command.target_url ?? null])).digest('hex')
    const old = this.jobs.get(command.check_id) ?? this.load(command.check_id)
    if (old) {
      if (old.request_digest !== digest) throw new Error('CHECK_ID_CONFLICT')
      this.jobs.set(old.check_id, old)
      if (['RUNNING', 'UNCONFIRMED'].includes(old.state) && !old.running) old.running = this.run(old, true)
      return this.public(old)
    }
    if ([...this.jobs.values()].filter(job => job.state === 'RUNNING').length >= 3) throw new Error('CHECK_CAPACITY_REACHED')
    if (this.jobs.size >= 500) {
      const oldest = [...this.jobs.values()].find(job => job.state !== 'RUNNING')
      if (!oldest) throw new Error('CHECK_CAPACITY_REACHED')
      this.jobs.delete(oldest.check_id)
    }
    const job = { check_id: command.check_id, service: command.service, request_digest: digest,
      scope_id: command.scope_id, target_url: command.target_url ?? TARGET, state: 'RUNNING',
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(), steps: [],
      verification_evidence: false, controller: new AbortController() }
    if (observeOnly && typeof knownJob === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(knownJob)) job.job_id = knownJob
    if (observeOnly) job.recovered = true
    this.persist(job) // write intent before the first potentially mutating tool call
    this.jobs.set(job.check_id, job)
    job.running = this.run(job, observeOnly)
    return this.public(job)
  }
  public(job) { const { controller, running, ...result } = job; return redact(result) }
  read(id, recovery) {
    let job = this.jobs.get(id)
    if (!job) {
      job = this.load(id)
      if (job) {
        this.jobs.set(id, job)
        if (['RUNNING', 'UNCONFIRMED'].includes(job.state)) job.running = this.run(job, true)
      } else if (recovery) return this.begin({ check_id: id, service: recovery.service, scope_id: recovery.scope_id,
        ...(recovery.service === 'testforge' ? { target_url: TARGET } : {}) }, true, recovery.job_id)
    }
    if (!job) throw new Error('CHECK_NOT_FOUND')
    if (['RUNNING', 'UNCONFIRMED'].includes(job.state) && !job.running && (job.job_id || job.session_id || job.memory_session_id)) {
      job.controller = new AbortController()
      job.running = this.run(job, true)
    }
    return this.public(job)
  }
  async run(job, observeOnly = false) {
    const timeout = setTimeout(() => job.controller.abort(), 420000)
    try {
      job.summary = await this[job.service](job, observeOnly)
      job.state = job.summary.pending ? 'UNCONFIRMED' : job.summary.passed ? 'SUCCEEDED' : 'FAILED'
    } catch (error) {
      job.state = job.controller.signal.aborted || (job.worker_dispatched && !/TESTFORGE_DEV_RUNNER_FAILED/.test(String(error?.message))) ? 'UNCONFIRMED' : 'FAILED'
      job.error = redact(String(error?.message ?? 'SERVICE_CHECK_FAILED'))
      const message = /Permission denied.*['"]\.env|EACCES.*\.env/i.test(job.error)
        ? 'Memory chưa đọc được dữ liệu vì dịch vụ phía máy chủ thiếu quyền truy cập tệp .env.'
        : /permission|403|401|unauthorized/i.test(job.error)
          ? 'Dịch vụ từ chối quyền truy cập. Cần kiểm tra credential hoặc quyền của dataset trên platform.'
          : job.service === 'sandbox' ? 'Sandbox chưa hoàn tất phép thử. Mở chi tiết để xem phản hồi của dịch vụ.'
            : job.service === 'testforge' ? 'TestForge chưa hoàn tất job. Mở chi tiết để xem lỗi đầu vào hoặc thực thi.'
              : 'Memory chưa hoàn tất lưu và tìm lại bản ghi. Mở chi tiết để xem phản hồi của dịch vụ.'
      job.summary = { passed: false, pending: job.state === 'UNCONFIRMED', message: job.state === 'UNCONFIRMED'
        ? 'Lượt kiểm tra bị gián đoạn; PokeDev sẽ lấy lại kết quả theo mã đã gửi, không tạo lại tác vụ.' : message }
    } finally {
      clearTimeout(timeout); job.updated_at = new Date().toISOString()
      try { this.persist(job) } catch { job.state = 'UNCONFIRMED'; job.error = 'CHECK_RECEIPT_STORE_UNAVAILABLE' }
      delete job.running
    }
  }
  async sandbox(job, observeOnly = false) {
    const workspace = 'pokedev-' + job.check_id
    const created = observeOnly ? null : await this.call(job, 'sandbox_create', { session_id: workspace, project_path: workspace,
      image: 'python:3.11-slim', cpu: '1', memory: '512Mi', ttl: 600 })
    const session = observeOnly ? job.session_id ?? workspace : created.sessionId ?? created.session_id ?? created.session?.id
    if (typeof session !== 'string' || !/^[A-Za-z0-9_-]{1,160}$/.test(session)) throw new Error('SANDBOX_CREATE_UNCONFIRMED')
    job.session_id = session
    this.persist(job)
    let ready = false
    for (let index = 0; index < 30; index++) {
      const status = await this.call(job, 'sandbox_status', { session_id: session })
      if (status.runnerConnected === true || status.runner_connected === true || status.session?.runnerConnected === true
          || (status.status === 'RUNNING' && status.runnerConnected === undefined)) { ready = true; break }
      await sleep(1000, job.controller.signal)
    }
    if (!ready) throw new Error('SANDBOX_RUNNER_NOT_READY')
    const marker = 'POKEDEV_SANDBOX_OK_' + job.check_id.replaceAll('-', '')
    await this.call(job, 'sandbox_write_file', { session_id: session, filepath: 'pokedev-probe.txt', contents: marker })
    const read = await this.call(job, 'sandbox_read_file', { session_id: session, filepath: 'pokedev-probe.txt', limit: 5 })
    const execution = await this.call(job, 'sandbox_shell', { session_id: session, timeout: 20,
      command: `python -c "from pathlib import Path; p=Path('pokedev-probe.txt'); assert p.read_text().strip()=='${marker}'; assert 2+2==4; print('${marker}')"` })
    const passed = execution.exitCode === 0 && String(execution.stdout ?? '').includes(marker) && JSON.stringify(read).includes(marker)
    return { passed, session_id: session, file_round_trip: JSON.stringify(read).includes(marker),
      exit_code: execution.exitCode, stdout: String(execution.stdout ?? '').slice(0, 2000), ttl_seconds: 600,
      message: passed ? 'Đã ghi/đọc tệp và chạy kiểm tra Python trong phiên sandbox riêng.' : 'Sandbox chưa trả kết quả Python đạt.' }
  }
  async memory(job, observeOnly = false) {
    const health = await this.call(job, 'memory_health', {})
    const session = 'pokedev-workflow-' + job.scope_id.slice(0, 16) + '-' + job.check_id
    const marker = 'PokeDevProbe' + job.check_id.replaceAll('-', '')
    job.memory_session_id = session
    this.persist(job)
    const client = new SessionMemoryClient(health.url, job.controller.signal)
    await client.initialize()
    if (!observeOnly) {
      const started = Date.now()
      const stored = await client.call('remember', { session_id: session,
        data: marker + ' synthetic workflow session context.', self_improvement: false })
      const text = (stored.content ?? []).map(item => item.text ?? '').join('\n')
      if (!text.includes('status=session_stored')) throw new Error('MEMORY_SESSION_WRITE_UNCONFIRMED')
      job.steps.push({ tool: 'MCP/remember (session cache)', duration_ms: Date.now() - started,
        result: { status: 'session_stored', session_id: session, graph_ingestion: false } })
      this.persist(job)
    }
    const started = Date.now()
    const recalled = await client.call('recall', { session_id: session, query: marker, top_k: 3 })
    const context = sessionContext(recalled, marker)
    job.steps.push({ tool: 'MCP/recall (session cache)', duration_ms: Date.now() - started,
      result: context ? { context, marker_found: true } : { marker_found: false } })
    return { passed: !!context, mode: 'SESSION_CACHE', memory_session_id: session,
      context: context ?? '', marker_found: !!context, permanent_graph_verified: false,
      synthesis_requested: false, graph_ingestion: false,
      message: context ? 'Đã lưu và tìm lại ngữ cảnh mẫu trong bộ nhớ phiên, không cần đọc tệp .env.'
        : 'Chưa tìm lại được bản ghi trong bộ nhớ phiên; chưa xác nhận dịch vụ hoạt động.' }
  }
  async testforge(job, observeOnly = false) {
    if (observeOnly && job.job_id?.startsWith('JOB-')) return this.testforgeBroker(job, true)
    return this.testforgeDev(job, observeOnly)
  }
  async testforgeDev(job, observeOnly = false) {
    const image = 'adlc-test-worker:local'
    const health = await this.call(job, 'testforge_health', {})
    if (health.sandbox_image !== image) throw new Error('TESTFORGE_WORKER_RELEASE_MISMATCH')
    const session = 'pokedev-testforge-' + job.check_id
    job.job_id = 'TFDEV-' + job.check_id.replaceAll('-', '')
    job.session_id = session
    job.execution_route = 'TESTFORGE_DEV_BUTTON_WORKER'
    this.persist(job)
    let execution
    if (!observeOnly) {
      const created = await this.call(job, 'sandbox_create', { session_id: session, project_path: session,
        image, cpu: '1', memory: '2Gi', ttl: 900 })
      if (created.sessionId !== session && created.session_id !== session) throw new Error('TESTFORGE_WORKER_CREATE_UNCONFIRMED')
      for (let index = 0; index < 20; index++) {
        const state = await this.call(job, 'sandbox_status', { session_id: session })
        if (state.status === 'RUNNING' || state.runnerConnected === true) break
        await sleep(1000, job.controller.signal)
      }
      const contents = readFileSync(new URL('./testforge-dev-login.py', import.meta.url), 'utf8')
      await this.call(job, 'sandbox_write_file', { session_id: session, filepath: 'pokedev-testforge-dev.py', contents })
      job.worker_dispatched = true
      this.persist(job)
      execution = await this.call(job, 'sandbox_shell', { session_id: session, timeout: 180,
        command: 'python pokedev-testforge-dev.py ' + job.check_id })
    }
    for (let index = 0; index < 120; index++) {
      if (!execution) execution = await this.call(job, 'sandbox_shell', { session_id: session, timeout: 15,
        command: `python -c "from pathlib import Path; import json; p=Path('pokedev-testforge-result.json'); print('POKEDEV_TESTFORGE_RESULT:'+(p.read_text() if p.is_file() else json.dumps({'pending':True})))"` })
      const line = String(execution.stdout ?? '').split(/\r?\n/).findLast(line => line.startsWith('POKEDEV_TESTFORGE_RESULT:'))
      if (!line) throw new Error(execution.exitCode != null ? 'TESTFORGE_DEV_RUNNER_FAILED' : 'TESTFORGE_DEV_RESULT_UNCONFIRMED')
      const report = JSON.parse(line.slice('POKEDEV_TESTFORGE_RESULT:'.length))
      if (!report.pending) {
        if (report.check_id !== job.check_id || report.framework !== 'TestForge TraceRecorder'
            || report.auth_mode !== 'DEV_BUTTON' || report.target_url !== TARGET || report.verification_evidence !== false) throw new Error('TESTFORGE_DEV_RESULT_SCOPE_MISMATCH')
        if (!report.execution_complete || report.checks_total !== 5) throw new Error('TESTFORGE_DEV_RUNNER_FAILED:' + String(report.error ?? 'INCOMPLETE'))
        return { passed: true, backend_status: 'completed', execution_route: job.execution_route, auth_mode: 'DEV_BUTTON',
          job_id: job.job_id, session_id: session, target_url: TARGET, report: redact(report),
          checks_total: report.checks_total, checks_passed: report.checks_passed,
          findings: report.checks.filter(check => check.status !== 'GROUNDED').map(check => ({ label: check.label,
            error: check.id === 'STEP-1-5' ? 'Khung nội dung nhúng trả về Not Found, đang trống hoặc chưa tải được.'
              : check.id === 'STEP-1-4' ? 'Chưa thấy liên kết Dashboard trong thanh điều hướng.'
                : check.id === 'STEP-1-3' ? 'Tiêu đề ứng dụng chưa hiển thị.'
                  : check.id === 'STEP-1-2' ? 'Chưa hoàn tất đăng nhập bằng nút Đăng nhập nhanh Dev.'
                    : 'Chưa mở được dashboard trong thời gian chờ.' })),
          application_passed: report.application_passed, application_verdict: report.application_passed ? 'Đạt phạm vi smoke' : 'Phát hiện lỗi',
          verification_verdict: 'NOT_ATTESTED',
          message: `TestForge đã chạy ${report.checks_total} kiểm tra qua Đăng nhập nhanh Dev; ${report.checks_passed} kiểm tra đạt.` }
      }
      execution = null
      await sleep(2000, job.controller.signal)
    }
    return { passed: false, pending: true, message: 'Worker TestForge chưa trả báo cáo cuối; hệ thống chỉ lấy lại kết quả, không chạy lại trình duyệt.' }
  }
  async testforgeBroker(job, observeOnly = false) {
    const health = await this.call(job, 'testforge_health', {})
    const target = job.target_url
    const input = { function_id: 'POKEDEV-DASHBOARD-' + job.check_id.slice(0, 8),
      feature: 'Dashboard TNQD chỉ đọc',
      precondition: ['Mở URL được cung cấp. Nếu cần, dùng nút Đăng nhập nhanh Dev có sẵn. Không nhập tài khoản hoặc mật khẩu mới.'],
      steps: ['Mở ' + target, 'Nếu có trang chào, chọn Đăng nhập nhanh Dev (Vào thẳng TNQD).',
        'Kiểm tra tiêu đề THANH NIÊN QUÂN ĐỘI và tab Đoàn viên & Tổ chức.',
        'Kiểm tra nội dung dashboard và iframe không có Not Found hoặc thông báo lỗi. Chỉ đọc, không thêm/sửa/xóa dữ liệu.'],
      expected_result: ['Dashboard và nội dung nhúng hiển thị bình thường, không có lỗi Not Found.'] }
    const accepted = observeOnly ? { job_id: job.job_id } : await this.call(job, 'testforge_explore', { input_inline: JSON.stringify(input),
      base_url: target, api_url: new URL(target).origin, email: '', actor: 'viewer', cleanup_template: '',
      video: false, headed: false, job_timeout_seconds: 240, wait_for_completion: false })
    const id = accepted.job_id
    if (observeOnly && !id) return { passed: false, pending: true, message: 'Platform đã khởi động lại trước khi xác nhận mã job. Cần người vận hành đối soát; PokeDev không tự gửi lại job.' }
    if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('TESTFORGE_CREATE_UNCONFIRMED')
    job.job_id = id
    this.persist(job)
    for (let index = 0; index < 130; index++) {
      const result = await this.call(job, 'testforge_result', { job_id: id, wait_for_completion: false })
      if (['completed', 'failed'].includes(result.status)) return { passed: result.status === 'completed',
        job_id: id, backend_status: result.status, target_url: target, report: redact(result),
        application_verdict: 'Chưa xác nhận',
        verification_verdict: 'NOT_ATTESTED',
        message: result.status === 'completed' ? 'TestForge đã hoàn tất job kiểm tra dashboard.' : 'TestForge trả về job không thành công; xem báo cáo để xác định nguyên nhân.' }
      await sleep(2000, job.controller.signal)
    }
    return { passed: false, job_id: id, target_url: target, health, message: 'Job đã tạo; chưa có kết quả cuối trong thời gian theo dõi.' }
  }
}

export function handler(checks, authenticate, productLoops, previews, tnqd, projectJobs) {
  return async (request, response) => {
    const send = (status, value) => { response.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' }); response.end(JSON.stringify(value)) }
    try {
      // Registered webServer routes bypass the /api transport's auth middleware.
      // Apply the same host/origin + signed browser cookie fence explicitly.
      const rejection = typeof authenticate === 'function' ? authenticate(request) : 503
      if (rejection !== undefined) return send(rejection, { error_code: rejection === 401 ? 'CHECK_UNAUTHENTICATED' : 'CHECK_ACCESS_DENIED' })
      const url = new URL(request.url, 'http://platform.local')
      const path = url.pathname
      if (path === PROJECT_ROOT || path.startsWith(PROJECT_ROOT + '/')) {
        const service = projectJobs?.()
        if (!service) return send(503, { error_code: 'PROJECT_RUNTIME_UNAVAILABLE' })
        return projectHandler(service, authenticate)(request, response)
      }
      if (path === TNQD_ROOT || path.startsWith(TNQD_ROOT + '/')) {
        const bridge = tnqd?.()
        if (!bridge) return send(503, { error_code: 'TNQD_RUNTIME_UNAVAILABLE' })
        return tnqdHandler(bridge, authenticate)(request, response)
      }
      if (path === PREVIEW_ROOT || path.startsWith(PREVIEW_ROOT + '/')) {
        const service = previews?.()
        if (!service) return send(503, { error_code: 'PREVIEW_RUNTIME_UNAVAILABLE' })
        return previewHandler(service, authenticate)(request, response)
      }
      if (path === LOOP_ROOT || path.startsWith(LOOP_ROOT + '/')) {
        const loops = productLoops?.()
        if (!loops) return send(503, { error_code: 'LOOP_RUNTIME_UNAVAILABLE' })
        return loopHandler(loops, authenticate)(request, response)
      }
      if (request.method === 'GET' && path === ROOT + '/capabilities') return send(200, checks.capabilities())
      const match = new RegExp('^' + ROOT + '/checks/([a-f0-9-]{36})$').exec(path)
      if (request.method === 'GET' && match) return send(200, checks.read(match[1], url.searchParams.has('scope_id')
        ? Object.fromEntries(url.searchParams) : undefined))
      if (request.method === 'POST' && path === ROOT + '/checks') {
        const chunks = []; let size = 0
        for await (const chunk of request) { size += chunk.length; if (size > 4096) throw new Error('CHECK_REQUEST_TOO_LARGE'); chunks.push(Buffer.from(chunk)) }
        return send(202, checks.begin(JSON.parse(Buffer.concat(chunks).toString('utf8'))))
      }
      return send(404, { error_code: 'CHECK_NOT_FOUND' })
    } catch (error) {
      const code = String(error?.message ?? '')
      return send(code === 'CHECK_NOT_FOUND' ? 404 : 409, { error_code: /^[A-Z_]+$/.test(code) ? code : 'CHECK_REQUEST_INVALID' })
    }
  }
}

export function apply(ctx, config = {}) {
  let productLoops, previews, tnqd, projectJobs
  const checks = new ServiceChecks(ctx, { dataDir: join(process.env.DSH_HOME ?? join(homedir(), '.dsh'), 'pokedev-services'), ...config })
  const authenticate = request => typeof ctx.connection?.requestRejection === 'function'
    ? ctx.connection.requestRejection(request) : 503
  tnqd = new TnqdBridge(checks, join(process.env.DSH_HOME ?? join(homedir(), '.dsh'), 'pokedev-tnqd'))
  projectJobs = new ProjectJobs(checks, join(process.env.DSH_HOME ?? join(homedir(), '.dsh'), 'pokedev-project-jobs'))
  ctx.effect(() => ctx.webServer.register({ kind: 'prefix', path: ROOT, handler: handler(checks, authenticate, () => productLoops, () => previews, () => tnqd, () => projectJobs) }))
  ctx.effect?.(() => () => { for (const job of checks.jobs.values()) job.controller.abort() })
  {
    // Native message value shape; no undeclared runtime package import in Hub installs.
    const createUserMessage = input => Object.freeze({ ...structuredClone(input), id: randomUUID(), role: 'user' })
    const home = process.env.DSH_HOME ?? join(homedir(), '.dsh')
    const loops = new ProductLoops(ctx, { dataDir: join(home, 'pokedev-product-loops'),
      workspaceDir: join(home, 'pokedev-product-workspaces'), createUserMessage,
      ...(config.loopModel ? { model: config.loopModel } : {}) })
    productLoops = loops
    previews = new ProductPreviews(loops, { dataDir: join(home, 'pokedev-previews') })
    try { registerProposalTool(ctx, loops) }
    catch (error) { loops.initializationError = { name: error?.name, code: error?.code,
      message: String(error?.message ?? '').replace(/([?&]token=)[^&\s]+/gi, '$1[redacted]').slice(0, 500) } }
    ctx.effect(() => () => {
      for (const handle of loops.handles.values()) handle.agent.cancel({ kind: 'user' })
    })
  }
}
