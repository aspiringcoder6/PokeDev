/**
 * vai-taskloop — Client-half (DeepSeek Harness Plugin)
 * 
 * Native DSH Right Sidebar Integration:
 * - Registered into `ctx.sidebarRightTabs` (claims *.task.json, *.taskloop.json, *task*.json, task-*.json)
 * - Renders into native slot `sidebar.right.pane.tab`
 * - Tab Title in `sidebar.right.pane.tab.title`
 * - Auto-reveals right sidebar on SSE events when Agent creates or updates a task
 * - Live bidirectional sync with interactive Task Contract Form
 */

window.__ModuleLoader__.load({
  id: "vai-taskloop",
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    const React = require("react")
    const { createElement: h, useState, useEffect, useRef, useCallback, Component } = React

    const NS = "vai-taskloop"
    const TAB_ID = "vai-taskloop-preview"
    const TAB_KIND = "taskloop"

    // ErrorBoundary to ensure host never crashes
    class SafeBoundary extends Component {
      constructor(props) {
        super(props)
        this.state = { hasError: false, error: null }
      }
      static getDerivedStateFromError(error) {
        return { hasError: true, error }
      }
      componentDidCatch(error, errorInfo) {
        console.error('[vai-taskloop] React render caught:', error, errorInfo)
      }
      render() {
        if (this.state.hasError) {
          return h('div', { style: { padding: '20px', color: '#ef4444', fontSize: '13px' } }, [
            h('div', { key: 'err_title', style: { fontWeight: '700' } }, 'Lỗi hiển thị TaskLoop'),
            h('button', {
              key: 'btn_retry',
              onClick: () => this.setState({ hasError: false }),
              style: { marginTop: '8px', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer' }
            }, 'Thử lại')
          ])
        }
        return this.props.children
      }
    }

    // Helper: open TaskLoop tab or resource
    function openTaskLoop(ctx, customAddress) {
      try {
        const curSession = ctx.sessions?.list?.getSnapshot()?.current || 'default'
        const address = customAddress || `dsh-resource://file/session/${curSession}/task.json`
        if (ctx.sidebarRight) {
          try {
            ctx.sidebarRight.openResource(address)
            return
          } catch (e) {
            ctx.sidebarRight.openTab?.(TAB_KIND)
          }
        }
      } catch (err) {
        console.warn('[vai-taskloop] openTaskLoop error:', err)
      }
    }

    // Native Tab Body Component (rendered inside right sidebar pane)
    function TaskLoopTabBody(props) {
      let tabInfo = null
      try {
        if (typeof props.useTabInfo === 'function') {
          tabInfo = props.useTabInfo()
        }
      } catch (e) {}

      const address = tabInfo?.tab?.navigation?.address || ''
      const curSession = props.sessionId || 'default'

      let fileParam = ''
      if (address) {
        if (address.startsWith('dsh-resource://file/')) {
          const matchSession = address.match(/dsh-resource:\/\/file\/session\/[^/]+\/(.+)$/)
          if (matchSession && matchSession[1]) {
            fileParam = '&file=' + encodeURIComponent(decodeURIComponent(matchSession[1]))
          } else {
            const rawPath = address.replace(/^dsh-resource:\/\/file\//, '')
            fileParam = '&file=' + encodeURIComponent(decodeURIComponent(rawPath))
          }
        } else if (address.startsWith('file://')) {
          const rawPath = address.replace(/^file:\/\//, '')
          fileParam = '&file=' + encodeURIComponent(decodeURIComponent(rawPath))
        }
      }

      return h('div', {
        style: {
          width: '100%',
          height: '100%',
          position: 'relative',
          background: '#ffffff',
          overflow: 'hidden'
        }
      }, [
        h('iframe', {
          key: `taskloop_frame_${curSession}_${address}`,
          src: `/api/taskloop/viewer/?session=${encodeURIComponent(curSession)}${fileParam}`,
          style: {
            width: '100%',
            height: '100%',
            border: 'none',
            display: 'block',
            background: '#ffffff'
          }
        })
      ])
    }

    // Native Tab Title Component
    function TaskLoopTabTitle(props) {
      let tabInfo = null
      try {
        if (typeof props.useTabInfo === 'function') {
          tabInfo = props.useTabInfo()
        }
      } catch (e) {}

      const address = tabInfo?.tab?.navigation?.address || ''
      let title = 'Task Contract'
      if (address) {
        const parts = address.split('/')
        title = decodeURIComponent(parts[parts.length - 1] || 'Task')
      }

      return h('span', {
        style: {
          display: 'inline-flex',
          alignItems: 'center',
          gap: '5px',
          fontWeight: '500'
        }
      }, [
        h('span', { key: 'icon', style: { fontSize: '13px' } }, '📋'),
        h('span', { key: 'txt' }, title)
      ])
    }

    // Plugin Definition
    exports.name = NS
    exports.inject = ['slots', 'sessions']
    exports.apply = function apply(ctx) {
      // 1. Register Tab Type and file patterns into ctx.sidebarRightTabs
      ctx.inject(['sidebarRightTabs'], (subCtx) => {
        subCtx.effect(() => subCtx.sidebarRightTabs.register({
          id: TAB_ID,
          kind: TAB_KIND,
          patterns: [
            '*.task.json',
            '*.taskloop.json',
            '*task*.json',
            'task-*.json',
            'dsh-page://sidebarRight/taskloop'
          ],
          priority: 'extension',
          title: (address) => {
            if (address && address.startsWith('dsh-resource://file/')) {
              const parts = address.split('/')
              return '📋 ' + decodeURIComponent(parts[parts.length - 1] || 'Task')
            }
            return '📋 TaskLoop'
          },
          guide: [{
            order: 25,
            title: () => '📋 TaskLoop',
            description: () => 'Biểu mẫu giao việc chuẩn cho Subagent'
          }]
        }), 'vai-taskloop: tab type registration')
      })

      // 2. Register Tab Body into slot `sidebar.right.pane.tab`
      ctx.effect(() => ctx.slots.inject('sidebar.right.pane.tab', () =>
        ctx.slots.register(
          { name: 'sidebar.right.pane.tab', key: TAB_ID },
          (props) => h(SafeBoundary, null, h(TaskLoopTabBody, props))
        )
      ), 'vai-taskloop: tab body')

      // 3. Register Tab Title into slot `sidebar.right.pane.tab.title`
      ctx.effect(() => ctx.slots.inject('sidebar.right.pane.tab.title', () =>
        ctx.slots.register(
          { name: 'sidebar.right.pane.tab.title', key: TAB_ID },
          (props) => h(SafeBoundary, null, h(TaskLoopTabTitle, props))
        )
      ), 'vai-taskloop: tab title')

      // 4. Realtime Auto-open on SSE events when Agent generates or updates task
      let es = null
      const hookSSE = (sessionId) => {
        if (es) { es.close(); es = null }
        if (!sessionId) return
        try {
          es = new EventSource(`/api/taskloop/events?session=${encodeURIComponent(sessionId)}`)
          const onEvent = () => {
            openTaskLoop(ctx)
          }
          es.addEventListener('task_created', onEvent)
          es.addEventListener('task_updated', onEvent)
        } catch (e) {
          console.warn('[vai-taskloop] SSE connection error:', e)
        }
      }

      ctx.effect(() => {
        const update = () => {
          const cur = ctx.sessions?.list?.getSnapshot()?.current
          hookSSE(cur)
        }
        update()
        return ctx.sessions?.list?.subscribe(update)
      }, 'vai-taskloop: sse auto-open')
    }

    return module.exports
  }
})
