/**
 * testforge-ai — DSH tools over the TestForge AI broker (FastAPI, Windows host).
 *
 * Tools registered (model-facing):
 *   testforge_health          — broker online + SUT/Agent Memory status
 *   testforge_explore         — Agent 1 explorer: 5-field JSON/Gherkin -> browser that
 *                               really runs, trace + video evidence          (long-running)
 *   testforge_replay          — replay fresh-state + Promotion Gate          (long-running)
 *   testforge_staging         — regression suite + JUnit + proofs            (long-running)
 *   testforge_perf            — Agent 2 k6 performance test + capacity       (long-running)
 *   testforge_fetch_testcase  — testcase recall from Agent Memory (GraphRAG) (fast)
 *   testforge_recommend       — Agent 3: PRUN FAIL -> likely causes + actions (long-running)
 *   testforge_result          — poll a long-running job result
 *
 * Connection config resolution (per call — hot-reload, same pattern as vai-sandbox):
 *   1. vault credentials (Settings -> Secrets tab): TESTFORGE_BROKER_URL, TESTFORGE_BROKER_TOKEN
 *   2. environment: same names
 *   3. plugin config (patch.yml): url / token
 *
 * Broker API (docs/27_plugin_harness_design.md):
 *   GET  /api/v1/health
 *   POST /api/v1/explore | /replay | /staging | /perf   -> 202 {job_id, poll_url}
 *   POST /api/v1/fetch-testcase                          -> raw GraphRAG recall JSON
 *   GET  /api/v1/result/{job_id}                         -> {status, exit_code, output...}
 */
import { defineTool } from '@deepseek-ai/dsh-tools'
import { credentialRef } from '@deepseek-ai/dsh-credentials'

export const name = 'testforge-ai'
export const inject = ['tools', 'credentials']

const DEFAULT_BROKER = 'http://10.0.10.195:9099'
const CONN_TIMEOUT_MS = 15000
const POLL_INTERVAL_MS = 5000
const DEFAULT_POLL_TIMEOUT_MS = 300000
const RESULT_CEILING_MS = 600000

/** Per-call connection resolution (vault first, then env, then plugin config). */
function makeResolver(ctx, config) {
  return async (key, fallback) => {
    try {
      const resolved = await ctx.credentials.resolve(credentialRef(key))
      if (resolved && typeof resolved.value === 'string' && resolved.value !== '') return resolved.value
    } catch { /* credentials service without a store / unset key */ }
    return process.env[key] ?? config[key] ?? fallback
  }
}

class BrokerError extends Error { }

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const t = setTimeout(resolve, ms)
  if (signal) signal.addEventListener('abort', () => { clearTimeout(t); reject(new Error('testforge request cancelled')) }, { once: true })
})

const isTransient = (err) => err instanceof BrokerError && !err.business
  || /fetch failed|ECONNRESET|ETIMEDOUT|EHOSTUNREACH|ECONNREFUSED|network|socket|aborted this fetch/i.test(String((err && err.cause) || (err && err.message) || err))

/** One broker request with 5xx/network retry; 4xx is a business result — verbatim, no retry. */
async function brokerFetch({ url, token, method = 'GET', body, signal, timeoutMs = CONN_TIMEOUT_MS }) {
  const headers = { accept: 'application/json' }
  if (body !== undefined) headers['content-type'] = 'application/json'
  if (token) headers.authorization = token.startsWith('Bearer ') ? token : `Bearer ${token}`
  let lastErr
  for (let attempt = 0; attempt < 3; attempt++) {
    const deadline = AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)])
    try {
      const res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: deadline })
      const text = await res.text()
      if (res.ok) {
        try { return JSON.parse(text) } catch { return text }
      }
      if (res.status >= 500 && attempt < 2) {
        lastErr = new BrokerError(`broker ${res.status} (upstream busy): ${text.slice(0, 120)}`)
        await sleep(500 * (attempt + 1), signal)
        continue
      }
      const businessError = new BrokerError(`broker HTTP ${res.status}: ${text.slice(0, 400)}`)
      businessError.business = true
      throw businessError
    } catch (err) {
      if (signal && signal.aborted) throw new Error('testforge request cancelled')
      if (!isTransient(err)) throw err
      lastErr = err
      if (attempt === 2) break
      await sleep(500 * (attempt + 1), signal)
    }
  }
  throw new BrokerError(`testforge broker unreachable after 3 attempts: ${url} (${(lastErr && (lastErr.cause || lastErr.message)) || lastErr})`)
}

const j = (value) => JSON.stringify(value)

function str(desc, extra = {}) { return { type: 'string', description: desc, ...extra } }
function num(desc, extra = {}) { return { type: 'number', ...extra, description: desc } }
function bool(desc) { return { type: 'boolean', description: desc } }

/**
 * Register the TestForge toolset.
 * @param ctx - cordis host context (tools + credentials).
 * @param config - optional plugin config: {url, token, pollTimeoutMs}.
 */
export function apply(ctx, config = {}) {
  const resolveCfg = makeResolver(ctx, config)

  const connection = async () => ({
    base: ((await resolveCfg('TESTFORGE_BROKER_URL')) || config.url || DEFAULT_BROKER).replace(/\/+$/, ''),
    token: (await resolveCfg('TESTFORGE_BROKER_TOKEN')) || config.token || '',
  })
  const pollTimeoutMs = () => Number(config.pollTimeoutMs) > 0 ? Number(config.pollTimeoutMs) : DEFAULT_POLL_TIMEOUT_MS

  /** POST a job endpoint, then poll GET /result/{job_id} until completed/failed
   *  or local timeout (plugin-side polling — agent needs just ONE call). On
   *  timeout the agent can still poll with testforge_result. */
  async function runJob({ path, body, signal, timeoutMs = pollTimeoutMs() }) {
    const { base, token } = await connection()
    const accepted = await brokerFetch({ url: `${base}${path}`, token, method: 'POST', body, signal, timeoutMs: CONN_TIMEOUT_MS })
    const jobId = accepted && accepted.job_id
    if (!jobId) return j(accepted)
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      await sleep(POLL_INTERVAL_MS, signal)
      const data = await brokerFetch({ url: `${base}/api/v1/result/${encodeURIComponent(jobId)}`, token, signal })
      if (data && (data.status === 'completed' || data.status === 'failed')) return j(data)
      if (signal && signal.aborted) throw new Error('testforge request cancelled')
    }
    return j({ job_id: jobId, status: 'running', note: `Plugin poll timeout sau ${Math.round(timeoutMs / 1000)}s — job VAN DANG CHAY tren broker. Poll tiep bang testforge_result {job_id: "${jobId}"}.` })
  }

  const T = defineTool
  const out = { schema: { type: 'string' }, render: (_a, v) => [{ type: 'text', text: v }] }

  ctx.tools.register(T({
    name: 'testforge_health',
    description: 'Kiem tra TestForge broker online: version, project_root, k6_installed, jobs_active, agent_memory (reachable) + auth_required. GOI TOOL NAY TRUOC moi luong test — neu SUT/Agent Memory chua san sang se duoc canh bao o day.',
    parameters: {},
    output: out,
    async execute(_args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: `${base}/api/v1/health`, token, signal: exec.signal })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_explore',
    description: 'Agent 1 Functional Test (explorer browser-first): chay browser Chromium that chong SUT tu requirement (5-field JSON hoac Gherkin .feature), thu thap trace/screenshot/video. LONG-RUNNING (60-300s) — tool poll giup, tra ket qua hoan thanh. input_json HOAC feature phai co; password KHONG truyen truc tiep — truyen ten env (password_env) da dat tren broker host.',
    parameters: {
      input_json: str('Path (tren broker host) den 5-field standard test input JSON, VD "opt/testspec/tteamflow_project_create.standard.json"'),
      feature: str('Path (tren broker host) den file .feature Gherkin (dung khi khong co input_json)'),
      base_url: str('Base URL cua SUT, VD "http://localhost"'),
      api_url: str('API base URL cua SUT, VD "http://localhost/api/v1"'),
      email: str('Email dang nhap SUT'),
      actor: str('Actor/role (mac dinh "admin")'),
      password_env: str('Ten ENV variable chua password tren broker host (mac dinh STAGING_TTEAMFLOW_ADMIN_PASSWORD)'),
      cleanup_template: str('URL template dọn dữ liệu sau test, VD "/projects/{id}"'),
      video: bool('Ghi video run (mac dinh false)'),
    },
    output: out,
    async execute(args, exec) {
      return runJob({ path: '/api/v1/explore', body: args, signal: exec.signal })
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_replay',
    description: 'Replay fresh-state mot session explore da co + Promotion Gate 10/10 checks. LONG-RUNNING (10-60s). Dung de verify spec co tai san duoc promote; heal: true bat self-healing locator (demo healing voi fault_locator).',
    parameters: {
      session: str('Session dir tu testforge_explore, VD "artifacts/automation/exploration/EXPLORE-xxxx"'),
      api_url: str('API base URL cua SUT'),
      email: str('Email dang nhap SUT'),
      password_env: str('Ten ENV variable chua password tren broker host'),
      cleanup_template: str('URL template dọn dữ liệu sau test'),
      heal: bool('Bat self-healing (mac dinh false)'),
      fault_locator: { type: 'array', items: { type: 'string' }, description: 'Locator inject fault de demo healing (co the lap nhieu locator)' },
    },
    output: out,
    async execute(args, exec) {
      return runJob({ path: '/api/v1/replay', body: args, signal: exec.signal })
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_staging',
    description: 'Chay regression suite staging (9/9 test case) + JUnit report + proofs. LONG-RUNNING (120-300s). profile = path den config/tteamflow.staging.docker.json, suite = path den opt/staging/*.json (deu tren broker host).',
    parameters: {
      profile: str('Path den staging profile JSON (tren broker host)'),
      suite: str('Path den staging suite JSON (tren broker host)'),
      output: str('Output dir (mac dinh artifacts/automation/staging)'),
      keep_runs: num('So run duoc giu lai (mac dinh 20)'),
    },
    output: out,
    async execute(args, exec) {
      return runJob({ path: '/api/v1/staging', body: args, signal: exec.signal })
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_perf',
    description: 'Agent 2 Performance Test (k6 + 3-tier threshold) + capacity report. LONG-RUNNING (30-300s). Chu y: perf kiem tra functional gate — neu staging chua PASS co the bi block (dung approved_by + justification khi co human override).',
    parameters: {
      requirement: str('Path (tren broker host) den perf requirement JSON, VD "opt/perf/perf_login.json"'),
      profile: str('Workload profile: normal | peak | stress | smoke (mac dinh normal)'),
      base_url: str('Base URL cua SUT (mac dinh http://localhost)'),
      users_json: str('Path den users.json cho auth (tren broker host)'),
      capacity_report: bool('Them capacity report (peak RPS, saturation, bottleneck signals)'),
      timeout_seconds: num('Timeout cho k6 run (mac dinh 600)'),
      staging_dir: str('Explicit path den STAGING run directory de kiem tra gate'),
      approved_by: str('HITL override — nguoi phe duyet (chi khi human da dong y)'),
      justification: str('Ly do override (bat buoc khi co approved_by)'),
    },
    output: out,
    async execute(args, exec) {
      return runJob({ path: '/api/v1/perf', body: args, signal: exec.signal })
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_fetch_testcase',
    description: 'Lay DU LIEU TESTCASE tu Agent Memory (GraphRAG recall: chunks + entities + related_chunks). dataset = ten dataset (VD "testforge-P01") hoac UUID id. query = tu khoa chuc nang (VD "FUNC-USER-ADD Add User"). KET QUA LA RAW CONTEXT — doc cac chunk, tu map ve 5-field Standard Test Input (function_id/feature/precondition/steps/expected_result) roi truyen cho testforge_explore; input thieu truong se bi broker-side validator chan. Can dataset moi? upload+cognify phai lam tren Agent Memory API/dashboard truoc.',
    parameters: {
      dataset: str('Ten hoac UUID dataset trong Agent Memory, VD "testforge-P01"'),
      query: str('Truy van tu nhien/tu khoa tim testcase'),
      function_id: str('function_id duoc noi vao query neu co, VD "FUNC-USER-ADD"'),
      top_k: num('So chunks tra ve 1-20 (mac dinh 5)'),
    },
    output: out,
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: `${base}/api/v1/fetch-testcase`, token, method: 'POST', body: args, signal: exec.signal, timeoutMs: 60000 })
      return j(data)
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_recommend',
    description: 'Agent 3 Recommendation: PRUN perf FAIL -> phan tich nguyen nhan (likely_causes + confidence) va de xuat hanh dong (recommendations, uu tien HIGH/MEDIUM/LOW). Tra REC-<id> JSON. LONG-RUNNING (30-120s khi co LLM; no_llm: true la heuristic nhanh). perf_run rong = tu lay PRUN FAIL moi nhat.',
    parameters: {
      perf_run: str('PRUN id can phan tich, VD "PRUN-abc123" (de rong = PRUN FAIL moi nhat)'),
      no_llm: bool('Chi heuristic Zero-LLM (nhanh, khong goi LLM)'),
      capacity: bool('Nap aggregated capacity report cung perf_req_id lam evidence'),
      context: str('Context them cho LLM (nginx config, SQL, thay doi gan day...)'),
    },
    output: out,
    async execute(args, exec) {
      return runJob({ path: '/api/v1/recommend', body: args, signal: exec.signal, timeoutMs: 180000 })
    },
  }))

  ctx.tools.register(T({
    name: 'testforge_result',
    description: 'Poll ket qua mot job TestForge theo job_id (JOB-xxxx). Chi can khi testforge_explore/replay/staging/perf tra ve "running" sau plugin poll timeout — goi lap lai cho den khi status = completed|failed.',
    parameters: { job_id: str('Job id, VD "JOB-a1b2c3d4"') },
    output: out,
    async execute(args, exec) {
      const { base, token } = await connection()
      const data = await brokerFetch({ url: `${base}/api/v1/result/${encodeURIComponent(String(args.job_id || '').trim())}`, token, signal: exec.signal })
      return j(data)
    },
  }))

  console.log('[testforge-ai] 8 tools registered')
}
