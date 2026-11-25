/**
 * vai-taskloop — SSE Realtime EventBus
 * 
 * Manages live Server-Sent Events subscriptions per session with global fallback.
 * Ensures the web form stays in sync with agent tool invocations in real time.
 */

export class TaskLoopEventBus {
  constructor() {
    this.clients = new Map() // sessionId -> Set of HTTP ServerResponse
    this.allClients = new Set() // all connected clients
    this.sessionSnapshots = new Map() // sessionId -> latest task JSON
    this.latestSnapshot = null
  }

  setSnapshot(sessionId, data) {
    this.sessionSnapshots.set(sessionId, data)
    this.latestSnapshot = data
  }

  getSnapshot(sessionId) {
    return this.sessionSnapshots.get(sessionId) || this.latestSnapshot || null
  }

  connect(res, sessionId) {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
      'Content-Encoding': 'none',
      'Access-Control-Allow-Origin': '*',
    })
    res.flushHeaders?.()
    res.write(': connected\n\n')

    if (!this.clients.has(sessionId)) {
      this.clients.set(sessionId, new Set())
    }
    const set = this.clients.get(sessionId)
    set.add(res)
    this.allClients.add(res)

    // Periodic ping to keep proxy/Nginx connection alive
    const pingTimer = setInterval(() => {
      try {
        res.write(': ping\n\n')
      } catch {
        clearInterval(pingTimer)
      }
    }, 15000)

    // Immediately send latest snapshot on connection if available
    const snapshot = this.getSnapshot(sessionId)
    if (snapshot) {
      res.write(`event: snapshot\ndata: ${JSON.stringify(snapshot)}\n\n`)
    }

    const cleanup = () => {
      clearInterval(pingTimer)
      set.delete(res)
      this.allClients.delete(res)
      if (set.size === 0) {
        this.clients.delete(sessionId)
      }
    }

    res.on('close', cleanup)
    res.on('finish', cleanup)
    res.on('error', cleanup)
  }

  broadcast(sessionId, eventName, payload) {
    if (payload) {
      this.setSnapshot(sessionId, payload)
    }

    const dataStr = JSON.stringify(payload ?? {})
    const msg = `event: ${eventName}\ndata: ${dataStr}\n\n`

    const specificSet = this.clients.get(sessionId)
    if (specificSet && specificSet.size > 0) {
      for (const client of specificSet) {
        try {
          client.write(msg)
        } catch {
          specificSet.delete(client)
          this.allClients.delete(client)
        }
      }
    } else {
      // Broadcast to all active clients as fallback
      for (const client of this.allClients) {
        try {
          client.write(msg)
        } catch {
          this.allClients.delete(client)
        }
      }
    }
  }
}
