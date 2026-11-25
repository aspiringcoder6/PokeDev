import { randomUUID } from 'node:crypto'
import { isAbsolute, resolve, sep } from 'node:path'

const DRIVER_REF = 'plugin:vai-adlc-driver-deepseek/0.2.0'
const DEFAULT_PROFILE_REF = 'harness-profile:adlc-coding/0.1.0'
const NATIVE_QUESTION_SOURCE = 'dsh.user-questions/request'
const NATIVE_APPROVAL_SOURCE = 'dsh.approval/request'

export class DeepSeekDriverError extends Error {
  constructor(code, message) {
    super(message)
    this.name = 'DeepSeekDriverError'
    this.code = code
  }
}

function requireObject(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', `${label} must be an object.`)
  }
  return value
}

function requireString(value, label) {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', `${label} must be a non-empty string.`)
  }
  return value.trim()
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function cloneJson(value) {
  return structuredClone(value)
}

function optionalString(value) {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined
}

function normalizeChoice(value) {
  return String(value)
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .replace(/đ/giu, 'd')
    .replace(/\s*\(recommended\)\s*$/iu, '')
    .trim()
    .toLowerCase()
}

function normalizeQuestions(rawQuestions) {
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) {
    throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', 'A native DSH question request must contain questions.')
  }
  const ids = new Set()
  return rawQuestions.map((rawQuestion, index) => {
    const question = requireObject(rawQuestion, `questions[${index}]`)
    const id = requireString(question.id, `questions[${index}].id`)
    if (ids.has(id)) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', `Native DSH question id ${JSON.stringify(id)} is duplicated.`)
    }
    ids.add(id)
    const options = Array.isArray(question.options)
      ? question.options.map((rawOption, optionIndex) => {
          const option = requireObject(rawOption, `questions[${index}].options[${optionIndex}]`)
          return {
            label: requireString(option.label, `questions[${index}].options[${optionIndex}].label`),
            ...(optionalString(option.description) === undefined ? {} : { description: optionalString(option.description) }),
          }
        })
      : []
    return {
      id,
      question: requireString(question.question, `questions[${index}].question`),
      ...(optionalString(question.header) === undefined ? {} : { header: optionalString(question.header) }),
      options,
      multiSelect: question.multiSelect === true || question.multi_select === true,
      ...(question.intent === null || typeof question.intent !== 'object' || Array.isArray(question.intent)
        ? {}
        : { intent: cloneJson(question.intent) }),
    }
  })
}

function approvalChoices(question) {
  if (question.multiSelect || question.options.length !== 2) return null
  const intentApprove = optionalString(question.intent?.approve)
  const approvePattern = /^(approve|allow|yes|confirm|continue|proceed|accept|dong y|phe duyet|chap nhan|cho phep|tiep tuc)$/u
  const rejectPattern = /^(reject|deny|no|cancel|request changes|revise|change|do not approve|tu choi|khong|huy|yeu cau sua|sua lai)$/u
  const approve = intentApprove === undefined
    ? question.options.find((option) => approvePattern.test(normalizeChoice(option.label)))
    : question.options.find((option) => option.label === intentApprove)
  const reject = question.options.find((option) => option !== approve && rejectPattern.test(normalizeChoice(option.label)))
  if (approve === undefined || reject === undefined) return null
  return { approve: approve.label, reject: reject.label }
}

function approvalSchema() {
  return {
    type: 'object',
    additionalProperties: false,
    properties: {
      action: { type: 'string', enum: ['approve', 'reject'] },
      comment: { type: 'string' },
    },
    required: ['action'],
  }
}

function publicQuestion(question) {
  return {
    id: question.id,
    question: question.question,
    ...(question.header === undefined ? {} : { header: question.header }),
    ...(question.options.length === 0 ? {} : { options: cloneJson(question.options) }),
    ...(question.multiSelect ? { multi_select: true } : {}),
  }
}

export function interactionFromUserQuestions(rawQuestions) {
  const questions = normalizeQuestions(rawQuestions)
  const choices = questions.length === 1 ? approvalChoices(questions[0]) : null
  if (choices !== null) {
    const [question] = questions
    return {
      interaction: {
        interaction_id: randomUUID(),
        kind: 'APPROVAL',
        title: question.header ?? 'Agent approval',
        prompt: question.question,
        schema_ref: null,
        input_schema: approvalSchema(),
        ui_schema: {},
        metadata: {
          bridge_source: NATIVE_QUESTION_SOURCE,
          native_questions: [publicQuestion(question)],
          native_response_mapping: choices,
        },
      },
      questions,
      answer(response) {
        const action = requireString(response?.action, 'interaction response.action')
        if (action !== 'approve' && action !== 'reject') {
          throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', 'Approval response.action must be approve or reject.')
        }
        const answer = { id: question.id, selected: [choices[action]] }
        const comment = optionalString(response?.comment)
        if (comment !== undefined) answer.custom = comment
        return { answers: [answer] }
      },
    }
  }

  const properties = Object.create(null)
  for (const question of questions) {
    const labels = question.options.map((option) => option.label)
    const base = {
      title: question.header ?? question.id,
      description: question.question,
    }
    properties[question.id] = question.multiSelect
      ? { ...base, type: 'array', items: { type: 'string', enum: labels } }
      : labels.length > 0
        ? { ...base, type: 'string', enum: labels }
        : { ...base, type: 'string' }
  }
  return {
    interaction: {
      interaction_id: randomUUID(),
      kind: 'FORM',
      title: questions.length === 1 ? questions[0].header ?? 'Agent question' : 'Agent questions',
      prompt: questions.map((question) => question.question).join('\n\n'),
      schema_ref: null,
      input_schema: {
        type: 'object',
        additionalProperties: false,
        properties,
        required: questions.map((question) => question.id),
      },
      ui_schema: {},
      metadata: {
        bridge_source: NATIVE_QUESTION_SOURCE,
        native_questions: questions.map(publicQuestion),
      },
    },
    questions,
    answer(response) {
      requireObject(response, 'interaction response')
      return {
        answers: questions.map((question) => {
          const value = response[question.id]
          const labels = new Set(question.options.map((option) => option.label))
          if (question.multiSelect) {
            if (!Array.isArray(value)) {
              throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', `interaction response.${question.id} must be an array.`)
            }
            const selected = value.map((item) => requireString(item, `interaction response.${question.id}`))
            if (selected.some((item) => !labels.has(item))) {
              throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', `interaction response.${question.id} contains an unknown option.`)
            }
            return { id: question.id, selected }
          }
          const text = requireString(value, `interaction response.${question.id}`)
          return labels.has(text)
            ? { id: question.id, selected: [text] }
            : { id: question.id, selected: [], custom: text }
        }),
      }
    },
  }
}

function displayReason(request) {
  if (typeof request.displayReason === 'string') return optionalString(request.displayReason)
  if (request.displayReason !== null && typeof request.displayReason === 'object' && !Array.isArray(request.displayReason)) {
    const english = optionalString(request.displayReason.en)
    if (english !== undefined) return english
    return Object.values(request.displayReason).map(optionalString).find((value) => value !== undefined)
  }
  return optionalString(request.reason)
}

export function interactionFromApprovalRequest(rawRequest) {
  const request = requireObject(rawRequest, 'approval request')
  const toolName = requireString(request.toolName, 'approval request.toolName')
  return {
    interaction: {
      interaction_id: randomUUID(),
      kind: 'APPROVAL',
      title: `Approve ${toolName}`,
      prompt: displayReason(request) ?? `Allow the agent to run ${toolName}?`,
      schema_ref: null,
      input_schema: approvalSchema(),
      ui_schema: {},
      metadata: {
        bridge_source: NATIVE_APPROVAL_SOURCE,
        tool_name: toolName,
        ...(optionalString(request.callId) === undefined ? {} : { tool_call_id: optionalString(request.callId) }),
        ...(optionalString(request.reason) === undefined ? {} : { reason: optionalString(request.reason) }),
      },
    },
    answer(response) {
      const action = requireString(response?.action, 'interaction response.action')
      if (action === 'approve') return 'allowed-once'
      if (action === 'reject') return 'rejected'
      throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', 'Approval response.action must be approve or reject.')
    },
  }
}

function jsonFromAssistantText(text) {
  const trimmed = text.trim()
  const fenced = /^```(?:json)?\s*([\s\S]*?)\s*```$/i.exec(trimmed)
  const candidate = fenced?.[1] ?? trimmed
  try {
    return JSON.parse(candidate)
  } catch (error) {
    throw new DeepSeekDriverError(
      'HARNESS_DRIVER_OUTPUT_INVALID',
      `The DeepSeek session did not return the required JSON envelope: ${error instanceof Error ? error.message : 'invalid JSON'}`,
    )
  }
}

function textFromContent(content) {
  if (!Array.isArray(content)) return ''
  return content
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
}

function failureFromTurnEvents(events) {
  const failedTurn = [...events].reverse().find((event) => (
    event?.type === 'turn/end'
      && event?.data?.reason?.kind === 'error'
      && event.data.reason.error !== null
      && typeof event.data.reason.error === 'object'
  ))
  if (failedTurn === undefined) return null
  const upstreamCode = optionalString(failedTurn.data.reason.error.code)?.toUpperCase()
  if (upstreamCode === 'TIMEOUT' || upstreamCode === 'ETIMEDOUT' || upstreamCode === 'REQUEST_TIMEOUT') {
    return {
      code: 'HARNESS_DRIVER_MODEL_TIMEOUT',
      message: 'The configured model provider timed out before producing an assistant response.',
    }
  }
  return {
    code: 'HARNESS_DRIVER_MODEL_FAILED',
    message: 'The configured model provider failed before producing an assistant response.',
  }
}

export function parseDriverEnvelope(text) {
  const envelope = requireObject(jsonFromAssistantText(text), 'driver envelope')
  if (envelope.kind === 'result') {
    return { kind: 'result', output: requireObject(envelope.output, 'driver result output') }
  }
  if (envelope.kind !== 'interaction') {
    throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', 'driver envelope.kind must be result or interaction.')
  }
  const interaction = requireObject(envelope.interaction, 'driver interaction')
  const kind = interaction.kind
  if (kind !== 'APPROVAL' && kind !== 'FORM') {
    throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', 'interaction.kind must be APPROVAL or FORM.')
  }
  const inputSchema = interaction.input_schema ?? {
    type: 'object',
    additionalProperties: false,
    properties: kind === 'APPROVAL'
      ? { action: { type: 'string', enum: ['approve', 'reject'] }, comment: { type: 'string' } }
      : {},
    required: kind === 'APPROVAL' ? ['action'] : [],
  }
  requireObject(inputSchema, 'interaction.input_schema')
  return {
    kind: 'interaction',
    interaction: {
      interaction_id: randomUUID(),
      kind,
      title: requireString(interaction.title, 'interaction.title'),
      prompt: requireString(interaction.prompt, 'interaction.prompt'),
      schema_ref: typeof interaction.schema_ref === 'string' ? interaction.schema_ref : null,
      input_schema: structuredClone(inputSchema),
      ui_schema: structuredClone(requireObject(interaction.ui_schema ?? {}, 'interaction.ui_schema')),
      metadata: structuredClone(requireObject(interaction.metadata ?? {}, 'interaction.metadata')),
    },
  }
}

function executionPrompt(request) {
  return [
    'You are executing one ADLC task inside DeepSeek Harness.',
    'Work only inside the configured workspace and obey the active Harness permissions.',
    'For the artifact-capture profile, edit the isolated local Git checkout at your session cwd using local filesystem/terminal tools. Do not use remote sandbox/VFS workspaces for this task. Do not apply, commit, push, fetch, or modify Git configuration. The publisher captures the actual diff; your source_patch URI is not evidence.',
    'When work is complete, respond with exactly one JSON object and no Markdown:',
    '{"kind":"result","output":{"summary":"...","outputs":{"source_patch":"workspace://..."}}}',
    'When a human decision or missing form value is required, prefer the ask_user_question tool; the ADLC bridge will present it to the operator and return the answer to this same session.',
    'If ask_user_question is unavailable, stop and respond with exactly:',
    '{"kind":"interaction","interaction":{"kind":"APPROVAL|FORM","title":"...","prompt":"...","input_schema":{"type":"object",...},"ui_schema":{},"metadata":{}}}',
    'Never place credentials, environment values, or raw secret material in either envelope.',
    '',
    `Objective: ${request.objective}`,
    `Operation: ${request.execution.operation}`,
    `Input: ${JSON.stringify(request.input)}`,
    `Context: ${JSON.stringify(request.context)}`,
    `Constraints: ${JSON.stringify(request.constraints)}`,
    `Required result schema: ${request.result_schema_ref}`,
  ].join('\n')
}

function continuationPrompt(interaction) {
  return [
    'The ADLC operator resolved the pending interaction.',
    `Interaction id: ${interaction.interaction_id}`,
    `Response: ${JSON.stringify(interaction.response)}`,
    'Continue the same task. Return either the final result envelope or one new interaction envelope.',
  ].join('\n')
}

export class DeepSeekHarnessExecutionDriver {
  constructor({ agents, agentDefaultModel, createUserMessage, profiles = {} }) {
    this.agents = agents
    this.agentDefaultModel = agentDefaultModel
    this.createUserMessage = createUserMessage
    this.profiles = structuredClone(profiles)
    this.handles = new Map()
    this.routes = new Map()
    this.agentSessions = new WeakMap()
    this.interactionWaiters = new Map()
    this.nativePending = new Map()
  }

  async health() {
    const profile = this.profiles[DEFAULT_PROFILE_REF]
    const profileRoutes = Object.fromEntries(Object.entries(this.profiles).map(([profileRef, candidate]) => [
      profileRef,
      {
        provider: optionalString(candidate?.provider) ?? null,
        model: optionalString(candidate?.model) ?? null,
      },
    ]))
    return {
      ready: Boolean(
        this.agents
          && this.createUserMessage
          && profile
          && profileRoutes[DEFAULT_PROFILE_REF]?.provider
          && profileRoutes[DEFAULT_PROFILE_REF]?.model,
      ),
      driver_ref: DRIVER_REF,
      profile_refs: Object.keys(this.profiles).sort(),
      profile_routes: profileRoutes,
    }
  }

  async start({ sessionId, request, workspace }) {
    return this._drive({ sessionId, request, workspace, prompt: executionPrompt(request), resume: false, interaction: null })
  }

  async continue({ sessionId, request, interaction, workspace }) {
    return this._drive({ sessionId, request, workspace, prompt: continuationPrompt(interaction), resume: true, interaction })
  }

  async cancel(sessionId) {
    const handle = this.handles.get(sessionId)
    if (handle === undefined) return false
    this._cancelNativeInteraction(sessionId)
    handle.agent.cancel({ kind: 'user' })
    await handle.dispose()
    this.agentSessions.delete(handle.agent)
    this.handles.delete(sessionId)
    this.routes.delete(sessionId)
    return true
  }

  async release(sessionId) {
    const handle = this.handles.get(sessionId)
    if (handle === undefined) return
    this._cancelNativeInteraction(sessionId)
    await handle.dispose()
    this.agentSessions.delete(handle.agent)
    this.handles.delete(sessionId)
    this.routes.delete(sessionId)
  }

  async close() {
    const handles = [...this.handles.values()]
    for (const sessionId of this.handles.keys()) this._cancelNativeInteraction(sessionId)
    this.handles.clear()
    for (const handle of handles) this.agentSessions.delete(handle.agent)
    this.routes.clear()
    await Promise.allSettled(handles.map((handle) => handle.dispose()))
  }

  async handleUserQuestions(request, next) {
    const sessionId = this._ownedSessionId(request?.agent)
    if (sessionId === undefined || !this.interactionWaiters.has(sessionId)) return next()
    const bridge = interactionFromUserQuestions(request.questions)
    return this._claimNativeInteraction({ sessionId, request, bridge, cancelValue: undefined })
  }

  async handleApprovalRequest(request, next) {
    const sessionId = this._ownedSessionId(request?.agent)
    if (sessionId === undefined || !this.interactionWaiters.has(sessionId)) return next()
    const bridge = interactionFromApprovalRequest(request)
    return this._claimNativeInteraction({ sessionId, request, bridge, cancelValue: 'cancelled' })
  }

  async _drive({ sessionId, request, prompt, resume, interaction, workspace }) {
    const handle = await this._handle(sessionId, request, resume, workspace)
    const agent = handle.agent
    const nativePending = this.nativePending.get(sessionId)
    if (nativePending !== undefined) {
      if (!resume || nativePending.bridge.interaction.interaction_id !== interaction?.interaction_id) {
        throw new DeepSeekDriverError('HARNESS_DRIVER_PROTOCOL_INVALID', 'The ADLC response does not match the pending native DSH interaction.')
      }
      return this._resumeNativeInteraction({ sessionId, agent, interaction, pending: nativePending })
    }
    const cursor = Number(agent.session.seq ?? agent.session.snapshotEvents().length)
    const waiter = this._startInteractionWaiter(sessionId)
    try {
      agent.followup(this.createUserMessage({
        content: [{ type: 'text', text: prompt }],
        source: { kind: 'plugin', plugin: 'vai-adlc-driver-deepseek', form: resume ? 'interaction-response' : 'task' },
      }))
    } catch (error) {
      this._clearInteractionWaiter(sessionId, waiter)
      throw error
    }
    return this._awaitAgentOutcome({ sessionId, agent, cursor, waiter })
  }

  async _resumeNativeInteraction({ sessionId, agent, interaction, pending }) {
    const cursor = Number(agent.session.seq ?? agent.session.snapshotEvents().length)
    const waiter = this._startInteractionWaiter(sessionId)
    try {
      pending.answer.resolve(pending.bridge.answer(interaction.response))
    } catch (error) {
      this._clearInteractionWaiter(sessionId, waiter)
      throw error
    }
    return this._awaitAgentOutcome({ sessionId, agent, cursor, waiter })
  }

  async _awaitAgentOutcome({ sessionId, agent, cursor, waiter }) {
    const completed = await Promise.race([
      Promise.resolve(agent.whenIdle()).then(() => ({ kind: 'idle' })),
      waiter.promise.then((pending) => ({ kind: 'interaction', pending })),
    ])
    this._clearInteractionWaiter(sessionId, waiter)
    if (completed.kind === 'interaction') {
      return {
        kind: 'interaction',
        interaction: cloneJson(completed.pending.bridge.interaction),
        trace_ref: `dsh-session://${sessionId}`,
        metadata: {
          ...this._routeMetadata(sessionId),
          bridge_source: completed.pending.bridge.interaction.metadata.bridge_source,
        },
      }
    }
    const events = agent.session.snapshotEvents(cursor)
    const assistant = [...events].reverse().find((event) => event.type === 'assistant/message')
    const text = textFromContent(assistant?.data?.message?.content)
    if (text === '') {
      const failure = failureFromTurnEvents(events)
      if (failure !== null) throw new DeepSeekDriverError(failure.code, failure.message)
      throw new DeepSeekDriverError('HARNESS_DRIVER_OUTPUT_MISSING', 'The DeepSeek session completed without assistant output.')
    }
    return {
      ...parseDriverEnvelope(text),
      trace_ref: `dsh-session://${sessionId}`,
      metadata: this._routeMetadata(sessionId),
    }
  }

  _routeMetadata(sessionId) {
    const route = this.routes.get(sessionId)
    return {
      driver_ref: DRIVER_REF,
      dsh_session_id: sessionId,
      ...(route === undefined ? {} : cloneJson(route)),
    }
  }

  async _claimNativeInteraction({ sessionId, request, bridge, cancelValue }) {
    if (this.nativePending.has(sessionId)) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_INTERACTION_CONFLICT', 'The DSH session already has a pending native interaction.')
    }
    const answer = deferred()
    const pending = { bridge, answer, cancelValue }
    this.nativePending.set(sessionId, pending)
    const waiter = this.interactionWaiters.get(sessionId)
    waiter.resolve(pending)

    const abort = () => {
      if (cancelValue !== undefined) answer.resolve(cancelValue)
      else answer.reject(new DeepSeekDriverError('HARNESS_DRIVER_INTERACTION_CANCELLED', 'The native DSH question was cancelled.'))
    }
    if (request.signal?.aborted) abort()
    else request.signal?.addEventListener?.('abort', abort, { once: true })
    try {
      return await answer.promise
    } finally {
      request.signal?.removeEventListener?.('abort', abort)
      if (this.nativePending.get(sessionId) === pending) this.nativePending.delete(sessionId)
    }
  }

  _startInteractionWaiter(sessionId) {
    if (this.interactionWaiters.has(sessionId)) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_EXECUTION_CONFLICT', 'The DSH session already has an active driver operation.')
    }
    const waiter = deferred()
    this.interactionWaiters.set(sessionId, waiter)
    return waiter
  }

  _clearInteractionWaiter(sessionId, waiter) {
    if (this.interactionWaiters.get(sessionId) === waiter) this.interactionWaiters.delete(sessionId)
  }

  _ownedSessionId(agent) {
    return agent !== null && typeof agent === 'object' ? this.agentSessions.get(agent) : undefined
  }

  _cancelNativeInteraction(sessionId) {
    const pending = this.nativePending.get(sessionId)
    if (pending === undefined) return
    if (pending.cancelValue !== undefined) pending.answer.resolve(pending.cancelValue)
    else pending.answer.reject(new DeepSeekDriverError('HARNESS_DRIVER_INTERACTION_CANCELLED', 'The native DSH question was cancelled.'))
    this.nativePending.delete(sessionId)
  }

  async _handle(sessionId, request, resume, workspace) {
    const existing = this.handles.get(sessionId)
    if (existing !== undefined) return existing
    const profile = this._profile(request.execution.profile_ref)
    const cwd = workspace?.cwd ?? profile.cwd
    const root = resolve(profile.workspaceRoot ?? profile.cwd)
    if (!isAbsolute(cwd) || (resolve(cwd) !== root && !resolve(cwd).startsWith(`${root}${sep}`))) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_PROFILE_INVALID', 'The execution workspace escapes its profile root.')
    }
    if (request.execution.profile_ref === 'harness-profile:adlc-coding-artifacts/0.1.0' && workspace === undefined) {
      throw new DeepSeekDriverError('HARNESS_ARTIFACT_WORKSPACE_MISSING', 'The artifact profile requires an isolated checkout.')
    }
    const agentOptions = {
      provider: profile.provider,
      model: profile.model,
      ...(profile.reasoningEffort ? { reasoningEffort: profile.reasoningEffort } : {}),
      ...(profile.maxTokens === undefined ? {} : { maxTokens: profile.maxTokens }),
    }
    const handle = resume
      ? await this.agents.resume({ resumeSessionId: sessionId, agentOptions })
      : await this.agents.create({
          sessionId,
          agentOptions,
          meta: { cwd, ...(profile.agentPreset ? { agentPreset: profile.agentPreset } : {}) },
        })
    this.handles.set(sessionId, handle)
    this.routes.set(sessionId, {
      profile_ref: request.execution.profile_ref,
      provider: agentOptions.provider,
      model: agentOptions.model,
    })
    this.agentSessions.set(handle.agent, sessionId)
    return handle
  }

  _profile(profileRef) {
    const profile = this.profiles[profileRef]
    if (profile === undefined) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_PROFILE_NOT_FOUND', `Unknown Harness execution profile: ${profileRef}`)
    }
    if (typeof profile.cwd !== 'string' || !isAbsolute(profile.cwd)) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_PROFILE_INVALID', 'Harness profile cwd must be absolute.')
    }
    const provider = optionalString(profile.provider)
    const model = optionalString(profile.model)
    if (provider === undefined || model === undefined) {
      throw new DeepSeekDriverError(
        'HARNESS_DRIVER_PROFILE_INVALID',
        'Harness execution profiles must pin both provider and model.',
      )
    }
    const cwd = resolve(profile.cwd)
    const workspaceRoot = resolve(profile.workspaceRoot ?? profile.cwd)
    if (cwd !== workspaceRoot && !cwd.startsWith(`${workspaceRoot}${sep}`)) {
      throw new DeepSeekDriverError('HARNESS_DRIVER_PROFILE_INVALID', 'Harness profile cwd escapes its workspace root.')
    }
    return { ...profile, provider, model, cwd }
  }
}

export { DRIVER_REF, DEFAULT_PROFILE_REF }
