import { createHash, createHmac, randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'

const CONTRACT_VERSION = '0.1'
const DRIVER_REF = 'plugin:vai-adlc-driver-deepseek/0.2.0'
const ATOMIC_REPLACE_RETRY_DELAYS_MS = [5, 10, 20, 40, 80]
const TERMINAL_STATUSES = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED'])
const SESSION_STATUSES = new Set([
  'ACCEPTED', 'PROVISIONING', 'RUNNING', 'WAITING_INTERACTION', 'VERIFYING',
  'READY_FOR_SUBMISSION', 'DELIVERING', ...TERMINAL_STATUSES,
])

export class HarnessRuntimeError extends Error {
  constructor(code, message, status = 400) {
    super(message)
    this.name = 'HarnessRuntimeError'
    this.code = code
    this.status = status
  }
}

function nowIso(clock) {
  return new Date(clock()).toISOString()
}

function clone(value) {
  return structuredClone(value)
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
}

function isTransientAtomicReplaceError(error) {
  return error?.code === 'EPERM' || error?.code === 'EBUSY' || error?.code === 'EACCES'
}

async function atomicReplace(source, destination) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      await rename(source, destination)
      return
    } catch (error) {
      const delayMs = ATOMIC_REPLACE_RETRY_DELAYS_MS[attempt]
      if (!isTransientAtomicReplaceError(error) || delayMs === undefined) throw error
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    }
  }
}

function requireObject(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID', `${label} must be an object.`, 422)
  }
  return value
}

function requireString(value, label) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID', `${label} must be a non-empty string.`, 422)
  }
  return value
}

function rejectUnknown(value, allowed, label) {
  const unknown = Object.keys(value).filter((key) => !allowed.has(key))
  if (unknown.length > 0) {
    throw new HarnessRuntimeError(
      'HARNESS_REQUEST_INVALID',
      `${label} contains unsupported fields: ${unknown.sort().join(', ')}.`,
      422,
    )
  }
}

export function validateSessionRequest(raw) {
  const request = requireObject(raw, 'session request')
  rejectUnknown(request, new Set([
    'schema_version', 'correlation', 'idempotency_key', 'objective', 'input', 'context',
    'constraints', 'execution', 'result_schema_ref', 'submission_mode', 'callback_ref', 'metadata',
  ]), 'session request')
  if (request.schema_version !== CONTRACT_VERSION) {
    throw new HarnessRuntimeError('HARNESS_CONTRACT_VERSION_UNSUPPORTED', 'Only Harness contract 0.1 is supported.', 422)
  }
  requireString(request.idempotency_key, 'idempotency_key')
  requireString(request.objective, 'objective')
  requireString(request.result_schema_ref, 'result_schema_ref')
  requireString(request.callback_ref, 'callback_ref')
  if (!['AUTO', 'MANUAL'].includes(request.submission_mode)) {
    throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID', 'submission_mode must be AUTO or MANUAL.', 422)
  }

  const correlation = requireObject(request.correlation, 'correlation')
  rejectUnknown(correlation, new Set(['request_id', 'workflow_run_id', 'task_run_id', 'attempt_id']), 'correlation')
  for (const field of ['request_id', 'workflow_run_id', 'task_run_id', 'attempt_id']) {
    requireString(correlation[field], `correlation.${field}`)
  }

  const execution = requireObject(request.execution, 'execution')
  rejectUnknown(execution, new Set(['profile_ref', 'operation', 'plugin_lock']), 'execution')
  requireString(execution.profile_ref, 'execution.profile_ref')
  requireString(execution.operation, 'execution.operation')
  if (!Array.isArray(execution.plugin_lock)) {
    throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID', 'execution.plugin_lock must be an array.', 422)
  }
  const pluginIds = new Set()
  for (const [index, rawEntry] of execution.plugin_lock.entries()) {
    const entry = requireObject(rawEntry, `execution.plugin_lock[${index}]`)
    rejectUnknown(entry, new Set(['plugin_id', 'version', 'content_digest', 'required']), `execution.plugin_lock[${index}]`)
    const pluginId = requireString(entry.plugin_id, `execution.plugin_lock[${index}].plugin_id`)
    requireString(entry.version, `execution.plugin_lock[${index}].version`)
    if (!/^sha256:[0-9a-f]{64}$/.test(entry.content_digest ?? '')) {
      throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID', `execution.plugin_lock[${index}].content_digest is invalid.`, 422)
    }
    if (pluginIds.has(pluginId)) {
      throw new HarnessRuntimeError('HARNESS_REQUEST_INVALID', 'execution.plugin_lock contains duplicate plugin ids.', 422)
    }
    pluginIds.add(pluginId)
  }
  requireObject(request.context, 'context')
  requireObject(request.constraints, 'constraints')
  requireObject(request.metadata, 'metadata')
  return clone(request)
}

export function validateInteractionResponse(raw) {
  const request = requireObject(raw, 'interaction response')
  rejectUnknown(request, new Set(['schema_version', 'response']), 'interaction response')
  if (request.schema_version !== CONTRACT_VERSION) {
    throw new HarnessRuntimeError('HARNESS_CONTRACT_VERSION_UNSUPPORTED', 'Only Harness contract 0.1 is supported.', 422)
  }
  return { schema_version: CONTRACT_VERSION, response: clone(requireObject(request.response, 'response')) }
}

function validateSchemaValue(value, schema, label) {
  if (schema.enum !== undefined && (!Array.isArray(schema.enum)
    || !schema.enum.some((item) => canonicalJson(item) === canonicalJson(value)))) {
    throw new HarnessRuntimeError('HARNESS_INTERACTION_RESPONSE_INVALID', `${label} is not an allowed value.`, 422)
  }
  const type = schema.type
  if (type === undefined) return
  const valid = type === 'string' ? typeof value === 'string'
    : type === 'boolean' ? typeof value === 'boolean'
      : type === 'number' ? typeof value === 'number' && Number.isFinite(value)
        : type === 'integer' ? Number.isInteger(value)
          : type === 'array' ? Array.isArray(value)
            : type === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value)
              : type === 'null' ? value === null
                : true
  if (!valid) {
    throw new HarnessRuntimeError('HARNESS_INTERACTION_RESPONSE_INVALID', `${label} must have JSON type ${type}.`, 422)
  }
  if (type === 'array' && schema.items !== null && typeof schema.items === 'object' && !Array.isArray(schema.items)) {
    value.forEach((item, index) => validateSchemaValue(item, schema.items, `${label}[${index}]`))
  }
}

function validateInteractionPayload(response, schema) {
  if (schema === null || typeof schema !== 'object' || Array.isArray(schema)) return
  validateSchemaValue(response, schema, 'response')
  if (schema.type !== 'object') return
  const properties = schema.properties && typeof schema.properties === 'object' ? schema.properties : {}
  const required = Array.isArray(schema.required) ? schema.required : []
  for (const field of required) {
    if (!(field in response)) {
      throw new HarnessRuntimeError('HARNESS_INTERACTION_RESPONSE_INVALID', `response.${field} is required.`, 422)
    }
  }
  if (schema.additionalProperties === false) {
    const unknown = Object.keys(response).filter((field) => !(field in properties))
    if (unknown.length > 0) {
      throw new HarnessRuntimeError(
        'HARNESS_INTERACTION_RESPONSE_INVALID',
        `response contains unsupported fields: ${unknown.sort().join(', ')}.`,
        422,
      )
    }
  }
  for (const [field, value] of Object.entries(response)) {
    if (properties[field] && typeof properties[field] === 'object') {
      validateSchemaValue(value, properties[field], `response.${field}`)
    }
  }
}

function toSessionRead(session) {
  return {
    schema_version: CONTRACT_VERSION,
    session_id: session.session_id,
    correlation: clone(session.request.correlation),
    idempotency_key: session.request.idempotency_key,
    status: session.status,
    submission_mode: session.request.submission_mode,
    events: clone(session.events),
    interactions: clone(session.interactions ?? []),
    result: session.result === null ? null : clone(session.result),
    delivery_id: session.delivery?.delivery_id ?? null,
    delivery_status: session.delivery?.status ?? null,
    created_at: session.created_at,
    updated_at: session.updated_at,
  }
}

function callbackSignature(secret, timestamp, body) {
  return `sha256=${createHmac('sha256', secret).update(`${timestamp}.`).update(body).digest('hex')}`
}

export class HarnessRuntime {
  constructor({ dataDir, callbackConfig, verifier, driver, artifactCollector, requiredPluginLock = [], fetchImpl = globalThis.fetch,
    clock = Date.now, autoDispatch = true, maxDeliveryAttempts = 8, pluginIntegrityVerifier }) {
    this.dataDir = dataDir
    this.storePath = join(dataDir, 'sessions.json')
    this.callbackConfig = callbackConfig
    this.verifier = verifier
    this.driver = driver
    this.artifactCollector = artifactCollector
    this.requiredPluginLock = clone(requiredPluginLock)
    this.fetchImpl = fetchImpl
    this.clock = clock
    this.autoDispatch = autoDispatch
    this.maxDeliveryAttempts = maxDeliveryAttempts
    this.pluginIntegrityVerifier = pluginIntegrityVerifier
    this.pluginIntegrity = {
      schema_version: CONTRACT_VERSION,
      ready: false,
      checked_at: nowIso(this.clock),
      error_code: 'HARNESS_PLUGIN_INTEGRITY_NOT_CONFIGURED',
      plugins: [],
    }
    this.sessions = new Map()
    this.idempotencyIndex = new Map()
    this.inflight = new Map()
    this._mutation = Promise.resolve()
    this._retryTimer = null
    this._integrityRefresh = null
    this._ready = this._initialize()
  }

  async _initialize() {
    await this._refreshPluginIntegrity()
    await this._load()
  }

  async _load() {
    await mkdir(this.dataDir, { recursive: true })
    let changed = false
    const accepted = []
    const autoSubmit = []
    try {
      const parsed = JSON.parse(await readFile(this.storePath, 'utf8'))
      if (!Array.isArray(parsed.sessions)) throw new Error('sessions must be an array')
      for (const session of parsed.sessions) {
        if (!SESSION_STATUSES.has(session.status)) continue
        session.interactions ??= []
        session.driver ??= { started: session.status !== 'ACCEPTED', metadata: {} }
        if (session.artifact_payloads?.length) {
          const retained = session.artifact_payloads.filter((captured) => session.result?.artifacts.some(
            (artifact) => artifact.artifact_id === captured.artifact_id && Date.parse(artifact.expires_at) > this.clock(),
          ))
          if (retained.length !== session.artifact_payloads.length) {
            session.artifact_payloads = retained
            changed = true
          }
        }
        if (session.delivery?.status === 'DELIVERING') {
          session.delivery.status = 'PENDING'
          session.delivery.next_attempt_at = this.clock()
          session.delivery.updated_at = nowIso(this.clock)
          changed = true
        }
        if (session.status === 'ACCEPTED') accepted.push(session.session_id)
        if (['PROVISIONING', 'RUNNING', 'VERIFYING'].includes(session.status)) {
          const previous = session.status
          this._recordEvent(session, 'execution.recovery_failed', previous, 'READY_FOR_SUBMISSION', {
            code: 'HARNESS_EXECUTION_INTERRUPTED',
          })
          session.result = this._failedResult(
            session,
            'HARNESS_EXECUTION_INTERRUPTED',
            'The Harness process restarted while the execution driver was active.',
          )
          changed = true
          if (session.request.submission_mode === 'AUTO') autoSubmit.push(session.session_id)
        }
        this.sessions.set(session.session_id, session)
        this.idempotencyIndex.set(session.request.idempotency_key, session.session_id)
      }
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
    if (changed) await this._persist()
    queueMicrotask(() => {
      if (this.pluginIntegrity.ready) {
        for (const sessionId of accepted) this._scheduleExecution(sessionId)
      }
      for (const sessionId of autoSubmit) {
        this._background('recovered automatic submission', this.submitSession(sessionId))
      }
      if (this.autoDispatch) this._scheduleOutbox(0)
    })
  }

  async close() {
    if (this._retryTimer !== null) clearTimeout(this._retryTimer)
    await this._ready
    await Promise.allSettled([...this.inflight.values()])
    await this._mutation
  }

  async health() {
    await this._ready
    const config = await this.callbackConfig()
    const callbackReady = Boolean(config.url && config.secret)
    const pluginLockReady = this.pluginIntegrity.ready
    const driverHealth = this.driver === undefined
      ? { ready: false, driver_ref: DRIVER_REF, profile_refs: [] }
      : await this.driver.health()
    const artifactHealth = this.artifactCollector === undefined ? { ready: true, profiles: {} } : await this.artifactCollector.health()
    return {
      service: 'vai-adlc-runtime',
      version: '0.3.0',
      contract_version: CONTRACT_VERSION,
      ready: callbackReady && pluginLockReady && driverHealth.ready && artifactHealth.ready,
      artifact_capture_ready: artifactHealth.ready,
      artifact_capture_profiles: clone(artifactHealth.profiles),
      callback_ready: callbackReady,
      plugin_lock_ready: pluginLockReady,
      plugin_integrity: clone(this.pluginIntegrity),
      storage_ready: true,
      execution_driver_ready: Boolean(driverHealth.ready),
      execution_driver: driverHealth.driver_ref ?? DRIVER_REF,
      execution_profiles: driverHealth.profile_refs ?? [],
      execution_profile_routes: clone(driverHealth.profile_routes ?? {}),
    }
  }

  async createSession(rawRequest) {
    await this._ready
    const request = validateSessionRequest(rawRequest)
    await this._refreshPluginIntegrity()
    this._ensurePluginLock(request.execution.plugin_lock)
    const callback = await this.callbackConfig()
    if (!callback.url || !callback.secret) {
      throw new HarnessRuntimeError('HARNESS_CALLBACK_NOT_CONFIGURED', 'The Harness callback destination is not configured.', 503)
    }
    if (request.callback_ref !== callback.ref) {
      throw new HarnessRuntimeError('HARNESS_CALLBACK_REF_NOT_ALLOWED', 'The requested callback reference is not allowed by this deployment.', 422)
    }
    const driverHealth = this.driver === undefined ? { ready: false } : await this.driver.health()
    if (!driverHealth.ready) {
      throw new HarnessRuntimeError('HARNESS_EXECUTION_DRIVER_UNAVAILABLE', 'The Harness execution driver is not ready.', 503)
    }
    const accepted = await this._mutate(async () => {
      const existingId = this.idempotencyIndex.get(request.idempotency_key)
      if (existingId !== undefined) {
        const existing = this.sessions.get(existingId)
        if (canonicalJson(existing.request) !== canonicalJson(request)) {
          throw new HarnessRuntimeError('HARNESS_IDEMPOTENCY_CONFLICT', 'The idempotency key is already bound to another session request.', 409)
        }
        return { schema_version: CONTRACT_VERSION, session: toSessionRead(existing), replayed: true }
      }
      if (request.execution.profile_ref === 'harness-profile:adlc-coding-artifacts/0.1.0') {
        const captureHealth = await this.artifactCollector?.health()
        if (captureHealth?.profiles?.[request.execution.profile_ref]?.ready !== true) {
          throw new HarnessRuntimeError(
            captureHealth?.profiles?.[request.execution.profile_ref]?.error_code ?? 'HARNESS_ARTIFACT_PLUGIN_UNAVAILABLE',
            'The deployment artifact source is not ready. No model turn was started.', 503,
          )
        }
      }
      const timestamp = nowIso(this.clock)
      const session = {
        session_id: randomUUID(), request, status: 'ACCEPTED', events: [], interactions: [], result: null,
        delivery: null, driver: { started: false, metadata: {} }, created_at: timestamp, updated_at: timestamp,
      }
      this._recordEvent(session, 'session.accepted', null, 'ACCEPTED')
      this.sessions.set(session.session_id, session)
      this.idempotencyIndex.set(request.idempotency_key, session.session_id)
      await this._persist()
      return { schema_version: CONTRACT_VERSION, session: toSessionRead(session), replayed: false }
    })
    if (!accepted.replayed) this._scheduleExecution(accepted.session.session_id)
    return accepted
  }

  async getSession(sessionId) {
    await this._ready
    const session = this.sessions.get(sessionId)
    if (session === undefined) {
      throw new HarnessRuntimeError('HARNESS_SESSION_NOT_FOUND', 'The Harness session was not found.', 404)
    }
    return toSessionRead(session)
  }

  async getArtifact(sessionId, artifactId) {
    await this._ready
    const session = this._requiredSession(sessionId)
    const artifact = session.result?.artifacts.find((item) => item.artifact_id === artifactId)
    const captured = session.artifact_payloads?.find((item) => item.artifact_id === artifactId)
    if (!artifact) {
      throw new HarnessRuntimeError('HARNESS_ARTIFACT_NOT_FOUND', 'The captured artifact was not found.', 404)
    }
    if (!artifact.expires_at || !Number.isFinite(Date.parse(artifact.expires_at)) || Date.parse(artifact.expires_at) <= this.clock()) {
      await this._mutate(async () => {
        session.artifact_payloads = (session.artifact_payloads ?? []).filter((item) => item.artifact_id !== artifactId)
        await this._persist()
      })
      throw new HarnessRuntimeError('HARNESS_ARTIFACT_EXPIRED', 'The captured artifact has expired.', 410)
    }
    if (!captured) {
      throw new HarnessRuntimeError('HARNESS_ARTIFACT_NOT_FOUND', 'The captured artifact bytes were not found.', 404)
    }
    return { schema_version: CONTRACT_VERSION, session_id: sessionId,
      correlation: clone(session.request.correlation), artifact: clone(artifact), payload_base64: captured.payload_base64 }
  }

  async getPluginInventory({ refresh = false } = {}) {
    await this._ready
    if (refresh) await this._refreshPluginIntegrity()
    return clone(this.pluginIntegrity)
  }

  async respondToInteraction(sessionId, interactionId, rawResponse) {
    await this._ready
    await this._refreshPluginIntegrity()
    const stored = this._requiredSession(sessionId)
    this._ensurePluginLock(stored.request.execution.plugin_lock)
    const payload = validateInteractionResponse(rawResponse)
    const resolved = await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      const interaction = session.interactions.find((candidate) => candidate.interaction_id === interactionId)
      if (interaction === undefined) {
        throw new HarnessRuntimeError('HARNESS_INTERACTION_NOT_FOUND', 'The Harness interaction was not found.', 404)
      }
      if (interaction.status === 'SUBMITTED') {
        if (canonicalJson(interaction.response) !== canonicalJson(payload.response)) {
          throw new HarnessRuntimeError('HARNESS_INTERACTION_RESPONSE_CONFLICT', 'The interaction already has a different response.', 409)
        }
        return { receipt: this._interactionReceipt(session, interaction, true), continuation: null }
      }
      if (session.status !== 'WAITING_INTERACTION' || interaction.status !== 'PENDING') {
        throw new HarnessRuntimeError('HARNESS_SESSION_STATE_CONFLICT', 'The interaction is not accepting a response.', 409)
      }
      validateInteractionPayload(payload.response, interaction.input_schema)
      interaction.status = 'SUBMITTED'
      interaction.response = clone(payload.response)
      interaction.resolved_at = nowIso(this.clock)
      this._recordEvent(session, 'interaction.submitted', 'WAITING_INTERACTION', 'RUNNING', {
        interaction_id: interaction.interaction_id,
      })
      await this._persist()
      return { receipt: this._interactionReceipt(session, interaction, false), continuation: clone(interaction) }
    })
    if (resolved.continuation !== null) this._scheduleExecution(sessionId, resolved.continuation)
    return resolved.receipt
  }

  async submitSession(sessionId) {
    return this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (session.delivery !== null) return this._submissionReceipt(session, true)
      if (session.status !== 'READY_FOR_SUBMISSION') {
        throw new HarnessRuntimeError('HARNESS_SESSION_STATE_CONFLICT', 'The session is not ready for submission.', 409)
      }
      if (session.result.artifacts.some((artifact) => Date.parse(artifact.expires_at) <= this.clock())) {
        throw new HarnessRuntimeError('HARNESS_ARTIFACT_EXPIRED', 'A source patch expired before submission.', 410)
      }
      session.delivery = {
        delivery_id: randomUUID(), status: 'PENDING', attempts: 0, created_at: nowIso(this.clock),
        updated_at: nowIso(this.clock), next_attempt_at: this.clock(), last_error: null,
      }
      this._recordEvent(session, 'delivery.enqueued', 'READY_FOR_SUBMISSION', 'DELIVERING', {
        delivery_id: session.delivery.delivery_id,
      })
      await this._persist()
      if (this.autoDispatch) queueMicrotask(() => this._background('outbox dispatch', this.flushOutbox()))
      return this._submissionReceipt(session, false)
    })
  }

  async cancelSession(sessionId) {
    const result = await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (TERMINAL_STATUSES.has(session.status)) return { read: toSessionRead(session), cancelDriver: false }
      if (session.delivery?.status === 'DELIVERED') {
        throw new HarnessRuntimeError('HARNESS_SESSION_STATE_CONFLICT', 'A delivered session cannot be cancelled.', 409)
      }
      const previous = session.status
      for (const interaction of session.interactions) {
        if (interaction.status === 'PENDING') {
          interaction.status = 'CANCELLED'
          interaction.resolved_at = nowIso(this.clock)
        }
      }
      this._recordEvent(session, 'session.cancelled', previous, 'CANCELLED')
      if (session.delivery !== null) {
        session.delivery.status = 'DEAD_LETTER'
        session.delivery.updated_at = nowIso(this.clock)
      }
      session.result = this._cancelledResult(session)
      await this._persist()
      return { read: toSessionRead(session), cancelDriver: true }
    })
    if (result.cancelDriver && this.driver !== undefined) {
      try {
        await this.driver.cancel(sessionId)
      } catch (error) {
        console.error(`[vai-adlc-runtime] driver cancellation failed: ${this._errorMessage(error)}`)
      }
    }
    return result.read
  }

  async flushOutbox() {
    await this._ready
    const due = [...this.sessions.values()]
      .filter((session) => session.delivery?.status === 'PENDING' && session.delivery.next_attempt_at <= this.clock())
      .map((session) => session.session_id)
    for (const sessionId of due) await this._deliver(sessionId)
    this._scheduleNextRetry()
  }

  _scheduleExecution(sessionId, continuation = null) {
    if (this.inflight.has(sessionId)) return
    const operation = this._execute(sessionId, continuation)
      .catch((error) => this._failExecution(sessionId, error))
      .finally(() => this.inflight.delete(sessionId))
    this.inflight.set(sessionId, operation)
  }

  async _execute(sessionId, continuation) {
    const execution = await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (TERMINAL_STATUSES.has(session.status)
        || ['WAITING_INTERACTION', 'READY_FOR_SUBMISSION', 'DELIVERING'].includes(session.status)) return null
      if (continuation === null) {
        if (session.status === 'ACCEPTED') {
          this._recordEvent(session, 'session.provisioning', 'ACCEPTED', 'PROVISIONING')
          this._recordEvent(session, 'session.running', 'PROVISIONING', 'RUNNING')
        } else if (session.status === 'PROVISIONING') {
          this._recordEvent(session, 'session.running', 'PROVISIONING', 'RUNNING')
        }
      } else if (session.status !== 'RUNNING') return null
      session.driver.started = true
      await this._persist()
      return { request: clone(session.request), continuation: continuation === null ? null : clone(continuation) }
    })
    if (execution === null) return
    const capturesArtifacts = this.artifactCollector?.supports(execution.request.execution.profile_ref) === true
    if (execution.request.execution.profile_ref === 'harness-profile:adlc-coding-artifacts/0.1.0' && !capturesArtifacts) {
      throw new HarnessRuntimeError('HARNESS_ARTIFACT_PLUGIN_UNAVAILABLE', 'The required artifact collector is not available.', 503)
    }
    const workspace = capturesArtifacts
      ? await this.artifactCollector.prepare({ sessionId, request: execution.request, resume: continuation !== null })
      : undefined
    const outcome = execution.continuation === null
      ? await this.driver.start({ sessionId, request: execution.request, workspace })
      : await this.driver.continue({ sessionId, request: execution.request, interaction: execution.continuation, workspace })
    if (outcome?.kind === 'interaction') {
      await this._waitForInteraction(sessionId, outcome)
      return
    }
    if (outcome?.kind !== 'result' || outcome.output === null
      || typeof outcome.output !== 'object' || Array.isArray(outcome.output)) {
      throw new HarnessRuntimeError('HARNESS_EXECUTION_DRIVER_INVALID_RESULT', 'The execution driver returned an invalid outcome.', 500)
    }
    await this._verifyAndComplete(sessionId, outcome)
  }

  async _waitForInteraction(sessionId, outcome) {
    await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (session.status !== 'RUNNING') return
      const requested = outcome.interaction
      if (requested === null || typeof requested !== 'object') {
        throw new HarnessRuntimeError('HARNESS_EXECUTION_DRIVER_INVALID_RESULT', 'The driver interaction is invalid.', 500)
      }
      const interaction = {
        interaction_id: requireString(requested.interaction_id, 'interaction.interaction_id'),
        kind: requested.kind,
        status: 'PENDING',
        title: requireString(requested.title, 'interaction.title'),
        prompt: requireString(requested.prompt, 'interaction.prompt'),
        schema_ref: typeof requested.schema_ref === 'string' ? requested.schema_ref : null,
        input_schema: clone(requireObject(requested.input_schema ?? {}, 'interaction.input_schema')),
        ui_schema: clone(requireObject(requested.ui_schema ?? {}, 'interaction.ui_schema')),
        requested_at: nowIso(this.clock), resolved_at: null, response: null,
        metadata: clone(requireObject(requested.metadata ?? {}, 'interaction.metadata')),
      }
      if (!['APPROVAL', 'FORM'].includes(interaction.kind)) {
        throw new HarnessRuntimeError('HARNESS_EXECUTION_DRIVER_INVALID_RESULT', 'The driver interaction kind is invalid.', 500)
      }
      if (session.interactions.some((candidate) => candidate.interaction_id === interaction.interaction_id)) {
        throw new HarnessRuntimeError('HARNESS_EXECUTION_DRIVER_INVALID_RESULT', 'The driver reused an interaction id.', 500)
      }
      session.interactions.push(interaction)
      session.driver.metadata = clone(outcome.metadata ?? {})
      session.driver.trace_ref = outcome.trace_ref ?? null
      this._recordEvent(session, 'interaction.requested', 'RUNNING', 'WAITING_INTERACTION', {
        interaction_id: interaction.interaction_id, kind: interaction.kind,
      })
      await this._persist()
    })
  }

  async _verifyAndComplete(sessionId, outcome) {
    const verification = await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (session.status !== 'RUNNING') return null
      const startedAt = nowIso(this.clock)
      this._recordEvent(session, 'verification.started', 'RUNNING', 'VERIFYING')
      session.driver.metadata = clone(outcome.metadata ?? {})
      session.driver.trace_ref = outcome.trace_ref ?? null
      await this._persist()
      return { request: clone(session.request), startedAt }
    })
    if (verification === null) return
    const capture = this.artifactCollector?.supports(verification.request.execution.profile_ref)
      ? await this.artifactCollector.collect({ sessionId, request: verification.request })
      : { artifacts: [], payloads: [] }
    const output = clone(outcome.output)
    if (capture.artifacts.length > 0) {
      // The source-patch reference is publisher-owned, never an agent's arbitrary URI.
      output.outputs = { ...(output.outputs ?? {}), source_patch: capture.artifacts[0].uri }
    }
    const reports = await this.verifier.verify({
      request: verification.request, sessionId, output, startedAt: verification.startedAt,
    })
    if (!Array.isArray(reports) || reports.length === 0) {
      throw new HarnessRuntimeError('HARNESS_VERIFIER_INVALID_RESULT', 'The configured verification plugin did not return a report.', 500)
    }
    const completed = await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (session.status !== 'VERIFYING') return false
      const verificationCompleted = nowIso(this.clock)
      this._recordEvent(session, 'verification.completed', 'VERIFYING', 'READY_FOR_SUBMISSION', {
        verifier_ref: reports[0].verifier_ref,
        status: reports.every((report) => report.status === 'PASSED') ? 'PASSED' : 'FAILED',
      })
      session.artifact_payloads = clone(capture.payloads)
      session.result = this._buildResult(session, output, reports, outcome, verificationCompleted, capture.artifacts)
      await this._persist()
      return session.request.submission_mode === 'AUTO'
    })
    await this.driver.release(sessionId)
    if (completed) queueMicrotask(() => this._background('automatic submission', this.submitSession(sessionId)))
  }

  async _failExecution(sessionId, error) {
    const shouldSubmit = await this._mutate(async () => {
      const session = this.sessions.get(sessionId)
      if (session === undefined || TERMINAL_STATUSES.has(session.status)
        || ['READY_FOR_SUBMISSION', 'DELIVERING'].includes(session.status)) return false
      const previous = session.status
      const code = typeof error?.code === 'string' ? error.code : 'HARNESS_EXECUTION_FAILED'
      this._recordEvent(session, 'execution.failed', previous, 'READY_FOR_SUBMISSION', { code })
      session.result = this._failedResult(session, code, this._safeExecutionMessage(code))
      await this._persist()
      return session.request.submission_mode === 'AUTO'
    })
    try {
      await this.driver?.release(sessionId)
    } catch (releaseError) {
      console.error(`[vai-adlc-runtime] driver release failed: ${this._errorMessage(releaseError)}`)
    }
    if (shouldSubmit) await this.submitSession(sessionId)
  }

  async _deliver(sessionId) {
    let deliveryEnvelope
    let config
    await this._mutate(async () => {
      const session = this._requiredSession(sessionId)
      if (session.delivery?.status !== 'PENDING') return
      config = await this.callbackConfig()
      session.delivery.status = 'DELIVERING'
      session.delivery.attempts += 1
      session.delivery.updated_at = nowIso(this.clock)
      if (!config.url || !config.secret) {
        this._deliveryFailure(session, 'callback is not configured')
        await this._persist()
        return
      }
      if (session.request.callback_ref !== config.ref) {
        this._deliveryFailure(session, 'callback reference is not allowed')
        await this._persist()
        return
      }
      deliveryEnvelope = {
        schema_version: CONTRACT_VERSION, delivery_id: session.delivery.delivery_id,
        callback_ref: session.request.callback_ref, created_at: session.delivery.created_at, result: clone(session.result),
      }
      await this._persist()
    })
    if (deliveryEnvelope === undefined) return
    const body = JSON.stringify(deliveryEnvelope)
    const timestamp = String(Math.floor(this.clock() / 1000))
    try {
      const response = await this.fetchImpl(config.url, {
        method: 'POST',
        headers: {
          accept: 'application/json', 'content-type': 'application/json',
          'x-adlc-delivery-id': deliveryEnvelope.delivery_id, 'x-adlc-timestamp': timestamp,
          'x-adlc-signature': callbackSignature(config.secret, timestamp, body),
        },
        body,
        signal: AbortSignal.timeout(15_000),
      })
      if (!response.ok) throw new Error(`callback returned HTTP ${response.status}`)
      await this._mutate(async () => {
        const session = this._requiredSession(sessionId)
        if (session.delivery?.delivery_id !== deliveryEnvelope.delivery_id) return
        session.delivery.status = 'DELIVERED'
        session.delivery.updated_at = nowIso(this.clock)
        session.delivery.last_error = null
        this._recordEvent(session, 'delivery.succeeded', 'DELIVERING', session.result.status, {
          delivery_id: deliveryEnvelope.delivery_id,
        })
        await this._persist()
      })
    } catch (error) {
      await this._mutate(async () => {
        const session = this._requiredSession(sessionId)
        if (session.delivery?.delivery_id !== deliveryEnvelope.delivery_id) return
        this._deliveryFailure(session, this._errorMessage(error))
        await this._persist()
      })
    }
  }

  _deliveryFailure(session, reason) {
    const delivery = session.delivery
    delivery.updated_at = nowIso(this.clock)
    delivery.last_error = String(reason).slice(0, 300)
    if (delivery.attempts >= this.maxDeliveryAttempts) {
      delivery.status = 'DEAD_LETTER'
      this._recordEvent(session, 'delivery.dead_lettered', session.status, 'FAILED', {
        delivery_id: delivery.delivery_id,
      })
      return
    }
    delivery.status = 'PENDING'
    const delays = [1_000, 5_000, 30_000, 120_000, 300_000]
    const retryIndex = Math.max(0, delivery.attempts - 1)
    delivery.next_attempt_at = this.clock() + delays[Math.min(retryIndex, delays.length - 1)]
  }

  _buildResult(session, output, verificationReports, outcome, completedAt, artifacts = []) {
    const verified = verificationReports.length > 0 && verificationReports.every((report) => report.status === 'PASSED')
    return {
      schema_version: CONTRACT_VERSION, session_id: session.session_id, correlation: clone(session.request.correlation),
      status: verified ? 'SUCCEEDED' : 'FAILED', output: clone(output), artifacts: clone(artifacts),
      verification_reports: clone(verificationReports), interaction_records: clone(session.interactions),
      plugin_lock: clone(session.request.execution.plugin_lock),
      metrics: {
        duration_ms: Math.max(0, Date.parse(completedAt) - Date.parse(session.created_at)),
        token_usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        custom: { execution_driver: DRIVER_REF },
      },
      trace_ref: outcome.trace_ref ?? session.driver.trace_ref ?? `harness://${session.session_id}/events`,
      error: verified ? null : {
        schema_version: CONTRACT_VERSION, error_id: randomUUID(), code: 'HARNESS_VERIFICATION_FAILED',
        category: 'EXECUTION', message: 'One or more Harness verification plugins rejected the candidate result.',
        retryable: false, service: 'vai-adlc-runtime',
        details: { verifier_refs: verificationReports.map((report) => report.verifier_ref) }, occurred_at: completedAt,
      },
      started_at: session.created_at, completed_at: completedAt,
      metadata: {
        execution_driver: DRIVER_REF, request_digest: `sha256:${sha256(canonicalJson(session.request))}`,
        driver: clone(outcome.metadata ?? session.driver.metadata ?? {}),
      },
    }
  }

  _failedResult(session, code, message) {
    const completedAt = nowIso(this.clock)
    return {
      schema_version: CONTRACT_VERSION, session_id: session.session_id, correlation: clone(session.request.correlation),
      status: 'FAILED', output: null, artifacts: [], verification_reports: [],
      interaction_records: clone(session.interactions ?? []), plugin_lock: clone(session.request.execution.plugin_lock),
      metrics: {
        duration_ms: Math.max(0, Date.parse(completedAt) - Date.parse(session.created_at)),
        token_usage: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        custom: { execution_driver: DRIVER_REF },
      },
      trace_ref: session.driver?.trace_ref ?? `harness://${session.session_id}/events`,
      error: {
        schema_version: CONTRACT_VERSION, error_id: randomUUID(), code, category: 'EXECUTION',
        message: String(message).slice(0, 500), retryable: false, service: 'vai-adlc-runtime',
        details: {}, occurred_at: completedAt,
      },
      started_at: session.created_at, completed_at: completedAt,
      metadata: {
        execution_driver: DRIVER_REF, request_digest: `sha256:${sha256(canonicalJson(session.request))}`,
        driver: clone(session.driver?.metadata ?? {}),
      },
    }
  }

  _cancelledResult(session) {
    const completedAt = nowIso(this.clock)
    const result = this._failedResult(session, 'HARNESS_SESSION_CANCELLED', 'The Harness session was cancelled.')
    result.status = 'CANCELLED'
    result.error.category = 'CANCELLED'
    result.completed_at = completedAt
    result.error.occurred_at = completedAt
    return result
  }

  _recordEvent(session, eventType, previousStatus, status, payload = {}) {
    session.status = status
    session.updated_at = nowIso(this.clock)
    session.events.push({
      schema_version: CONTRACT_VERSION, event_id: randomUUID(), session_id: session.session_id,
      sequence: session.events.length + 1, event_type: eventType, previous_status: previousStatus,
      status, occurred_at: session.updated_at, payload,
    })
  }

  _interactionReceipt(session, interaction, replayed) {
    return {
      schema_version: CONTRACT_VERSION, session_id: session.session_id,
      interaction: clone(interaction), status: session.status, replayed,
    }
  }

  _submissionReceipt(session, replayed) {
    return {
      schema_version: CONTRACT_VERSION, session_id: session.session_id, status: session.status,
      delivery_id: session.delivery.delivery_id, delivery_status: session.delivery.status, replayed,
    }
  }

  _requiredSession(sessionId) {
    const session = this.sessions.get(sessionId)
    if (session === undefined) {
      throw new HarnessRuntimeError('HARNESS_SESSION_NOT_FOUND', 'The Harness session was not found.', 404)
    }
    return session
  }

  _ensurePluginLock(pluginLock) {
    if (this.requiredPluginLock.length === 0) {
      throw new HarnessRuntimeError('HARNESS_PLUGIN_LOCK_NOT_CONFIGURED', 'The Harness deployment has no trusted plugin lock.', 503)
    }
    if (!this.pluginIntegrity.ready) {
      throw new HarnessRuntimeError(
        this.pluginIntegrity.error_code ?? 'HARNESS_PLUGIN_INTEGRITY_FAILED',
        'The installed Harness plugins do not match the trusted deployment lock.',
        503,
      )
    }
    if (canonicalJson(pluginLock) !== canonicalJson(this.requiredPluginLock)) {
      throw new HarnessRuntimeError('HARNESS_PLUGIN_LOCK_MISMATCH', 'The requested plugin lock does not match the trusted Harness deployment.', 409)
    }
  }

  async _refreshPluginIntegrity() {
    if (this._integrityRefresh !== null) return this._integrityRefresh
    this._integrityRefresh = (async () => {
      if (typeof this.pluginIntegrityVerifier !== 'function') {
        this.pluginIntegrity = {
          schema_version: CONTRACT_VERSION,
          ready: false,
          checked_at: nowIso(this.clock),
          error_code: 'HARNESS_PLUGIN_INTEGRITY_NOT_CONFIGURED',
          plugins: [],
        }
        return
      }
      try {
        const report = await this.pluginIntegrityVerifier(clone(this.requiredPluginLock))
        if (report === null || typeof report !== 'object' || Array.isArray(report)
          || report.schema_version !== CONTRACT_VERSION || typeof report.ready !== 'boolean'
          || !Array.isArray(report.plugins)) {
          throw new Error('plugin integrity verifier returned an invalid report')
        }
        this.pluginIntegrity = clone(report)
      } catch {
        this.pluginIntegrity = {
          schema_version: CONTRACT_VERSION,
          ready: false,
          checked_at: nowIso(this.clock),
          error_code: 'HARNESS_PLUGIN_INTEGRITY_CHECK_FAILED',
          plugins: [],
        }
      }
    })().finally(() => {
      this._integrityRefresh = null
    })
    return this._integrityRefresh
  }

  _mutate(operation) {
    const run = async () => {
      await this._ready
      return operation()
    }
    const current = this._mutation.then(run, run)
    this._mutation = current.then(() => undefined, () => undefined)
    return current
  }

  async _persist() {
    const snapshot = { schema_version: CONTRACT_VERSION, sessions: [...this.sessions.values()] }
    await mkdir(dirname(this.storePath), { recursive: true })
    const temporary = `${this.storePath}.${process.pid}.${randomUUID()}.tmp`
    await writeFile(temporary, JSON.stringify(snapshot, null, 2), { encoding: 'utf8', mode: 0o600 })
    try {
      await atomicReplace(temporary, this.storePath)
    } catch (error) {
      await unlink(temporary).catch(() => undefined)
      throw error
    }
  }

  _scheduleOutbox(delayMs) {
    if (this._retryTimer !== null) clearTimeout(this._retryTimer)
    this._retryTimer = setTimeout(() => this._background('outbox retry', this.flushOutbox()), delayMs)
    this._retryTimer.unref?.()
  }

  _background(label, operation) {
    void operation.catch((error) => {
      console.error(`[vai-adlc-runtime] ${label} failed: ${this._errorMessage(error)}`)
    })
  }

  _errorMessage(error) {
    return error instanceof Error ? error.message : 'unknown error'
  }

  _safeExecutionMessage(code) {
    if (code.startsWith('HARNESS_ARTIFACT_')) {
      return 'The workspace source patch could not be safely captured. No patch was accepted.'
    }
    if (code === 'HARNESS_EXECUTION_INTERRUPTED') {
      return 'The Harness process restarted while the execution driver was active.'
    }
    if (code === 'HARNESS_DRIVER_MODEL_TIMEOUT') {
      return 'The configured model provider timed out before producing an assistant response.'
    }
    if (code === 'HARNESS_DRIVER_MODEL_FAILED') {
      return 'The configured model provider failed before producing an assistant response.'
    }
    if (code.startsWith('HARNESS_VERIFIER_')) {
      return 'The Harness verifier could not produce an accepted report.'
    }
    if (code.startsWith('HARNESS_DRIVER_') || code === 'HARNESS_EXECUTION_DRIVER_INVALID_RESULT') {
      return 'The DeepSeek execution driver did not produce a valid structured outcome.'
    }
    return 'The Harness execution did not complete successfully.'
  }

  _scheduleNextRetry() {
    const timestamps = [...this.sessions.values()]
      .filter((session) => session.delivery?.status === 'PENDING')
      .map((session) => session.delivery.next_attempt_at)
    if (timestamps.length === 0) return
    this._scheduleOutbox(Math.max(0, Math.min(...timestamps) - this.clock()))
  }
}

export { callbackSignature }
