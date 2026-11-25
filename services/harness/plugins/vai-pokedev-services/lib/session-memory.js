/** Cognee session-cache transport; graph ingestion and synthesis are disabled. */
export class SessionMemoryClient {
  constructor(url, signal, transport = fetch) {
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.pathname !== '/mcp'
        || parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error('MEMORY_ENDPOINT_INVALID')
    this.url = parsed.href; this.signal = signal; this.transport = transport; this.next = 0
    this.headers = { 'content-type': 'application/json', accept: 'application/json, text/event-stream' }
  }
  async rpc(method, params, notification = false) {
    const id = notification ? undefined : ++this.next
    const response = await this.transport(this.url, { method: 'POST', headers: this.headers,
      signal: AbortSignal.any([this.signal, AbortSignal.timeout(45000)]),
      body: JSON.stringify({ jsonrpc: '2.0', ...(id ? { id } : {}), method, params }) })
    if (!response.ok) throw new Error('MEMORY_SESSION_HTTP_' + response.status)
    const session = response.headers.get('mcp-session-id')
    if (session) this.headers['mcp-session-id'] = session
    if (notification) { await response.body?.cancel(); return {} }
    const reader = response.body.getReader(), decoder = new TextDecoder()
    let pending = '', total = 0
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (value) { total += value.length; pending += decoder.decode(value, { stream: true }) }
        if (total > 524288) throw new Error('MEMORY_SESSION_RESPONSE_TOO_LARGE')
        const candidates = []
        if (pending.trimStart().startsWith('{')) candidates.push(pending)
        else {
          const lines = pending.split(/\r?\n/)
          pending = done ? '' : lines.pop()
          for (const line of lines) if (line.startsWith('data:')) candidates.push(line.slice(5).trim())
        }
        for (const candidate of candidates) {
          let message
          try { message = JSON.parse(candidate) } catch { continue }
          if (message.id !== id) continue
          if (message.error || !message.result || message.result.isError) throw new Error('MEMORY_SESSION_CALL_FAILED')
          return message.result
        }
        if (done) throw new Error('MEMORY_SESSION_RESPONSE_INVALID')
      }
    } finally { await reader.cancel().catch(() => {}) }
  }
  async initialize() {
    const result = await this.rpc('initialize', { protocolVersion: '2025-03-26', capabilities: {},
      clientInfo: { name: 'PokeDev-workflow-session-memory', version: '0.1.0' } })
    this.headers['MCP-Protocol-Version'] = result.protocolVersion
    await this.rpc('notifications/initialized', {}, true)
    const listed = await this.rpc('tools/list', {})
    if (!['remember', 'recall'].every(name => listed.tools?.find(tool => tool.name === name)?.inputSchema?.properties?.session_id)) {
      throw new Error('MEMORY_SESSION_MODE_UNSUPPORTED')
    }
  }
  async call(name, args) { return this.rpc('tools/call', { name, arguments: args }) }
}

export function sessionContext(result, marker) {
  const context = (result?.content ?? []).filter(item => item.type === 'text').map(item => item.text).join('\n')
  return context.includes('[session] ' + marker + ' synthetic workflow session context.') ? context.slice(0, 6000) : null
}
