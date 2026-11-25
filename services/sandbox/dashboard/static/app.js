let currentSessions = [];
let selectedSessionId = '';
let commandHistory = [];
let historyIndex = -1;
let isExecuting = false;
let autoRefreshTimer = null;
let currentActionMode = 'shell';

function toggleAutoRefresh(enabled) {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
  if (enabled) {
    autoRefreshTimer = setInterval(fetchTopology, 3000);
  }
}

async function fetchTopology() {
  const tbody = document.getElementById('topology-rows');
  const statSessions = document.getElementById('stat-sessions');
  const statRunners = document.getElementById('stat-runners');
  const statSandboxes = document.getElementById('stat-sandboxes');
  const statResources = document.getElementById('stat-resources');
  const lastUpdate = document.getElementById('last-update');
  const topologyCount = document.getElementById('topology-count');

  try {
    let res = await fetch('/api/v1/management/sessions');
    if (!res.ok) res = await fetch('/debug/sessions');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    currentSessions = await res.json();
    
    // Active / Connected sessions
    const connectedSessions = currentSessions.filter(s => s.runnerConnected || s.status === 'READY');
    statSessions.textContent = currentSessions.length;
    
    const uniqueRunners = new Set(currentSessions.map(s => s.runnerId).filter(r => r && r !== 'none (standby)'));
    const uniqueSandboxes = new Set(currentSessions.map(s => s.sandboxId).filter(Boolean));
    
    statRunners.textContent = uniqueRunners.size;
    statSandboxes.textContent = uniqueSandboxes.size;
    if (topologyCount) topologyCount.textContent = `${currentSessions.length} Active`;

    // Calculate resources
    let totalCpu = 0;
    let totalMemGi = 0;
    currentSessions.forEach(s => {
      totalCpu += parseInt(s.cpu || '2', 10);
      const memStr = (s.memory || '4Gi').replace(/Gi?/i, '');
      totalMemGi += parseInt(memStr, 10) || 4;
    });
    statResources.textContent = `${totalCpu} vCPU / ${totalMemGi} GB`;

    updateSessionDropdown(currentSessions);

    if (currentSessions.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="9" class="empty-state">
            No active sessions or sandboxes registered.<br>
            Click <strong>"🚀 Provision Session & Sandbox"</strong> or <strong>"⚡ Create Standby Sandbox"</strong> above.
          </td>
        </tr>
      `;
    } else {
      tbody.innerHTML = currentSessions.map(session => {
        const sid = session.sessionId || 'N/A';
        const rid = session.runnerId || 'none (standby)';
        const sboxId = session.sandboxId || 'N/A';
        const status = session.status || 'READY';
        const image = session.image || 'ubuntu:latest';
        const cpu = session.cpu || '2';
        const mem = session.memory || '4Gi';
        const ttl = session.ttl ? `${session.ttl}s (${(session.ttl/3600).toFixed(1)}h)` : '1h';
        const workspace = session.workspace || '/workspace';

        const isSelected = sid === selectedSessionId;
        const isStandby = status === 'STANDBY' || !session.runnerConnected;

        let statusBadge = `
          <span class="status-badge status-ready">
            <span class="pulse"></span>
            ${escapeHtml(status)}
          </span>
        `;
        if (isStandby) {
          statusBadge = `
            <span class="status-badge status-standby">
              <span class="pulse pulse-purple"></span>
              STANDBY
            </span>
          `;
        }

        let actionButtons = `
          <div class="action-btn-group">
            <button class="btn-xs ${isSelected ? 'btn-selected' : ''}" onclick="selectSessionTerminal('${escapeHtml(sid)}')">
              ${isSelected ? '✓ Active' : '💻 Select'}
            </button>
            ${isStandby ? `
              <button class="btn-xs btn-purple-xs" onclick="attachRunner('${escapeHtml(sid)}', '${escapeHtml(sboxId)}', '${escapeHtml(workspace)}')">
                ▶ Attach
              </button>
            ` : ''}
            <button class="btn-xs btn-danger-xs" title="Terminate session and destroy container" onclick="terminateSession('${escapeHtml(sid)}')">
              🗑️
            </button>
          </div>
        `;

        return `
          <tr class="${isSelected ? 'row-selected' : ''}">
            <td>
              <span class="code-tag tag-blue" onclick="copyToClipboard('${escapeHtml(sid)}')">
                ${escapeHtml(sid)} 📋
              </span>
            </td>
            <td><span class="code-tag ${isStandby ? 'tag-muted' : 'tag-purple'}">${escapeHtml(rid)}</span></td>
            <td><span class="code-tag tag-green">${escapeHtml(sboxId)}</span></td>
            <td><span class="code-tag tag-amber">${escapeHtml(image)}</span></td>
            <td><span class="code-tag tag-blue">${escapeHtml(cpu)} CPU / ${escapeHtml(mem)}</span></td>
            <td class="text-muted-sm">${escapeHtml(ttl)}</td>
            <td>${statusBadge}</td>
            <td><span class="code-tag tag-muted">${escapeHtml(workspace)}</span></td>
            <td>${actionButtons}</td>
          </tr>
        `;
      }).join('');
    }

    lastUpdate.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
  } catch (err) {
    console.error('Failed to fetch topology:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty-state state-error">
          Failed to load topology from Broker: ${escapeHtml(err.message)}
        </td>
      </tr>
    `;
  }
}

function updateSessionDropdown(sessions) {
  const select = document.getElementById('terminal-session-select');
  const prevSelected = select.value;

  if (sessions.length === 0) {
    select.innerHTML = '<option value="">-- No Active Session Available --</option>';
    selectedSessionId = '';
    updatePromptLabel();
    return;
  }

  select.innerHTML = sessions.map(s => {
    const sid = s.sessionId;
    const sbox = s.sandboxId || 'sbx';
    const status = s.runnerConnected ? 'CONNECTED' : 'STANDBY';
    return `<option value="${escapeHtml(sid)}">${escapeHtml(sid)} (${escapeHtml(sbox)} - ${status})</option>`;
  }).join('');

  if (prevSelected && sessions.some(s => s.sessionId === prevSelected)) {
    select.value = prevSelected;
    selectedSessionId = prevSelected;
  } else if (!selectedSessionId || !sessions.some(s => s.sessionId === selectedSessionId)) {
    selectedSessionId = sessions[0].sessionId;
    select.value = selectedSessionId;
  }
  updatePromptLabel();
}

function onSessionSelectChange() {
  const select = document.getElementById('terminal-session-select');
  selectedSessionId = select.value;
  updatePromptLabel();
  fetchTopology();
}

function selectSessionTerminal(sessionId) {
  selectedSessionId = sessionId;
  const select = document.getElementById('terminal-session-select');
  if (select) select.value = sessionId;
  updatePromptLabel();
  fetchTopology();
  
  const termSection = document.getElementById('terminal-section');
  if (termSection) {
    termSection.scrollIntoView({ behavior: 'smooth' });
  }
}

function updatePromptLabel() {
  const prompt = document.getElementById('terminal-prompt');
  if (selectedSessionId) {
    prompt.textContent = `root@opensandbox[${selectedSessionId.substring(0, 10)}]:/workspace$`;
  } else {
    prompt.textContent = `root@opensandbox:/workspace$`;
  }
}

async function launchEnvironment(createSandboxOnly = false) {
  const pathInput = document.getElementById('launch-project-path');
  const imageSelect = document.getElementById('launch-image');
  const cpuSelect = document.getElementById('launch-cpu');
  const memorySelect = document.getElementById('launch-memory');
  const ttlSelect = document.getElementById('launch-ttl');
  const btnFull = document.getElementById('btn-launch-full');
  const btnStandby = document.getElementById('btn-launch-standby');
  const btnTextFull = document.getElementById('launch-full-text');
  const btnTextStandby = document.getElementById('launch-standby-text');

  const projectPath = pathInput.value.trim() || '/home/ntkien/sandbox-kit';
  const image = imageSelect.value;
  const cpu = cpuSelect ? cpuSelect.value : '2';
  const memory = memorySelect ? memorySelect.value : '4Gi';
  const ttl = parseInt(ttlSelect.value, 10);

  if (createSandboxOnly) {
    btnStandby.disabled = true;
    btnTextStandby.innerHTML = '<span class="spinner"></span> Creating Standby Sandbox...';
  } else {
    btnFull.disabled = true;
    btnTextFull.innerHTML = '<span class="spinner"></span> Provisioning Session & Sandbox...';
  }

  try {
    let res = await fetch('/api/v1/management/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_path: projectPath,
        image: image,
        cpu: cpu,
        memory: memory,
        ttl: ttl,
        create_sandbox_only: createSandboxOnly
      }),
    });
    if (!res.ok) {
      res = await fetch('/session/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_path: projectPath,
          image: image,
          cpu: cpu,
          memory: memory,
          ttl: ttl,
          create_sandbox_only: createSandboxOnly
        }),
      });
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    appendTerminalLog(`[Broker] Provisioned session '${data.sessionId}' (Sandbox: '${data.sandboxId}', CPU: ${cpu}, Mem: ${memory}).`, 'INFO');

    for (let i = 0; i < 3; i++) {
      await new Promise(r => setTimeout(r, 600));
      await fetchTopology();
    }
  } catch (err) {
    alert(`Failed to provision session: ${err.message}`);
    appendTerminalLog(`[Provisioning Error] ${err.message}`, 'ERR');
  } finally {
    btnFull.disabled = false;
    btnStandby.disabled = false;
    btnTextFull.textContent = '🚀 + Provision Session & Sandbox (Native)';
    btnTextStandby.textContent = '⚡ + Create Standby Sandbox Only';
  }
}

async function attachRunner(sessionId, sandboxId, projectPath) {
  appendTerminalLog(`[Launcher] Attaching Standalone Runner to Sandbox '${sandboxId}' for session '${sessionId}'...`, 'INFO');

  try {
    let res = await fetch(`/api/v1/management/sessions/${sessionId}/attach-runner`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        sandbox_id: sandboxId,
        project_path: projectPath || '/home/ntkien/sandbox-kit'
      })
    });
    if (!res.ok) {
      res = await fetch('/api/sandboxes/attach-runner', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          sandbox_id: sandboxId,
          project_path: projectPath || '/home/ntkien/sandbox-kit'
        })
      });
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    appendTerminalLog(`[Launcher] ${data.message}`, 'INFO');

    for (let i = 0; i < 4; i++) {
      await new Promise(r => setTimeout(r, 800));
      await fetchTopology();
    }
  } catch (err) {
    alert(`Failed to attach runner: ${err.message}`);
    appendTerminalLog(`[Attach Error] ${err.message}`, 'ERR');
  }
}

async function terminateSession(sessionId) {
  if (!confirm(`Are you sure you want to terminate session '${sessionId}' and destroy its OpenSandbox container?`)) {
    return;
  }

  appendTerminalLog(`[Broker] Terminating session '${sessionId}'...`, 'INFO');

  try {
    let res = await fetch(`/api/v1/management/sessions/${sessionId}`, {
      method: 'DELETE',
    });
    if (!res.ok) {
      res = await fetch(`/session/${sessionId}`, {
        method: 'DELETE',
      });
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    appendTerminalLog(`[Broker] ${data.message}`, 'INFO');
    if (selectedSessionId === sessionId) {
      selectedSessionId = '';
    }
    await fetchTopology();
  } catch (err) {
    alert(`Failed to terminate session: ${err.message}`);
    appendTerminalLog(`[Terminate Error] ${err.message}`, 'ERR');
  }
}

function switchActionMode(mode) {
  currentActionMode = mode;
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.mode-panel').forEach(panel => panel.classList.remove('active'));

  const activeTab = document.getElementById(`tab-${mode}`);
  const activePanel = document.getElementById(`mode-panel-${mode}`);
  if (activeTab) activeTab.classList.add('active');
  if (activePanel) activePanel.classList.add('active');

  const presetContainer = document.getElementById('preset-container');
  if (presetContainer) {
    presetContainer.style.display = mode === 'shell' ? 'flex' : 'none';
  }
}

async function executeCommandFromInput() {
  if (isExecuting) return;

  const input = document.getElementById('terminal-input');
  const cmd = input.value.trim();
  if (!cmd) return;

  if (!selectedSessionId) {
    alert('Please select an active session or launch a new sandbox environment first!');
    return;
  }

  if (commandHistory.length === 0 || commandHistory[commandHistory.length - 1] !== cmd) {
    commandHistory.push(cmd);
  }
  historyIndex = commandHistory.length;

  input.value = '';
  await runTerminalCommand(cmd);
}

async function runTerminalCommand(command) {
  const btn = document.getElementById('btn-execute');
  const consoleElem = document.getElementById('terminal-console');

  isExecuting = true;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Executing';

  const startTime = Date.now();

  try {
    let res = await fetch('/api/v1/agent/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: selectedSessionId,
        action: {
          runShellCommand: {
            command: command,
            timeout: 120,
          }
        }
      })
    });
    if (!res.ok) {
      res = await fetch('/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: selectedSessionId,
          action: {
            runShellCommand: {
              command: command,
              timeout: 120,
            }
          }
        })
      });
    }

    const duration = ((Date.now() - startTime) / 1000).toFixed(2);

    if (!res.ok) {
      const errText = await res.text();
      renderExecutionOutput(command, '', `Error (${res.status}): ${errText}`, 1, duration);
      return;
    }

    const data = await res.json();
    let stdout = data.stdout || data.response || '';
    let stderr = data.stderr || data.error || '';
    let exitCode = data.exitCode !== undefined && data.exitCode !== null ? data.exitCode : 0;

    if (typeof stderr === 'object') {
      stderr = JSON.stringify(stderr, null, 2);
    }

    renderExecutionOutput(command, stdout, stderr, exitCode, duration);
  } catch (err) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(2);
    renderExecutionOutput(command, '', `Failed to execute: ${err.message}`, 1, duration);
  } finally {
    isExecuting = false;
    btn.disabled = false;
    btn.textContent = 'Execute';
    consoleElem.scrollTop = consoleElem.scrollHeight;
  }
}

async function executeListDir() {
  if (!selectedSessionId) {
    alert('Please select an active target session first!');
    return;
  }

  const path = document.getElementById('ls-path-input').value.trim() || '/workspace';
  const box = document.getElementById('ls-result-box');
  box.innerHTML = '<div class="spinner-row"><span class="spinner"></span> Listing directory...</div>';

  try {
    let res = await fetch('/api/v1/agent/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: selectedSessionId,
        action: {
          listDirectory: { path: path }
        }
      })
    });
    if (!res.ok) {
      res = await fetch('/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: selectedSessionId,
          action: {
            listDirectory: { path: path }
          }
        })
      });
    }

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    box.innerHTML = `<pre class="json-code">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  } catch (err) {
    box.innerHTML = `<div class="error-msg">Error listing directory: ${escapeHtml(err.message)}</div>`;
  }
}

async function executeReadFile() {
  if (!selectedSessionId) {
    alert('Please select an active target session first!');
    return;
  }

  const path = document.getElementById('read-path-input').value.trim() || '/workspace/package.json';
  const box = document.getElementById('read-result-box');
  box.innerHTML = '<div class="spinner-row"><span class="spinner"></span> Reading file...</div>';

  try {
    let res = await fetch('/api/v1/agent/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: selectedSessionId,
        action: {
          readFiles: { files: [{ path: path }] }
        }
      })
    });
    if (!res.ok) {
      res = await fetch('/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: selectedSessionId,
          action: {
            readFiles: { files: [{ path: path }] }
          }
        })
      });
    }

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    box.innerHTML = `<pre class="json-code">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  } catch (err) {
    box.innerHTML = `<div class="error-msg">Error reading file: ${escapeHtml(err.message)}</div>`;
  }
}

async function executeFileInfo() {
  if (!selectedSessionId) {
    alert('Please select an active target session first!');
    return;
  }

  const path = document.getElementById('info-path-input').value.trim() || '/workspace';
  const box = document.getElementById('info-result-box');
  box.innerHTML = '<div class="spinner-row"><span class="spinner"></span> Fetching file info...</div>';

  try {
    let res = await fetch('/api/v1/agent/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: selectedSessionId,
        action: {
          getFileInfo: { path: path }
        }
      })
    });
    if (!res.ok) {
      res = await fetch('/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: selectedSessionId,
          action: {
            getFileInfo: { path: path }
          }
        })
      });
    }

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    box.innerHTML = `<pre class="json-code">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  } catch (err) {
    box.innerHTML = `<div class="error-msg">Error getting file info: ${escapeHtml(err.message)}</div>`;
  }
}

function renderExecutionOutput(command, stdout, stderr, exitCode, durationSec) {
  const consoleElem = document.getElementById('terminal-console');
  const exitClass = exitCode === 0 ? 'exit-success' : 'exit-fail';
  const exitLabel = `EXIT ${exitCode}`;

  const entry = document.createElement('div');
  entry.className = 'terminal-log-entry';

  entry.innerHTML = `
    <div class="terminal-cmd-line">
      <span class="terminal-prompt-text">root@opensandbox[${escapeHtml(selectedSessionId.substring(0, 8))}]:/workspace$</span>
      <span>${escapeHtml(command)}</span>
      <span class="exit-tag ${exitClass}">${exitLabel}</span>
      <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: auto;">${durationSec}s</span>
    </div>
    ${stdout ? `<div class="terminal-output">${escapeHtml(stdout)}</div>` : ''}
    ${stderr ? `<div class="terminal-stderr">${escapeHtml(stderr)}</div>` : ''}
  `;

  consoleElem.appendChild(entry);
}

function appendTerminalLog(msg, type = 'INFO') {
  const consoleElem = document.getElementById('terminal-console');
  if (!consoleElem) return;
  const entry = document.createElement('div');
  entry.className = 'terminal-log-entry';
  entry.innerHTML = `
    <div style="color: ${type === 'ERR' ? 'var(--accent-red)' : 'var(--accent-blue)'}; font-weight: 500;">
      ${escapeHtml(msg)}
    </div>
  `;
  consoleElem.appendChild(entry);
  consoleElem.scrollTop = consoleElem.scrollHeight;
}

function insertPreset(cmd) {
  const input = document.getElementById('terminal-input');
  if (input) {
    input.value = cmd;
    input.focus();
  }
}

function clearTerminal() {
  const consoleElem = document.getElementById('terminal-console');
  if (consoleElem) {
    consoleElem.innerHTML = '<div class="console-welcome">Console output cleared. Ready for command execution.</div>';
  }
}

function handleTerminalKeydown(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    executeCommandFromInput();
  } else if (e.key === 'ArrowUp') {
    if (commandHistory.length > 0 && historyIndex > 0) {
      historyIndex--;
      e.target.value = commandHistory[historyIndex];
    }
  } else if (e.key === 'ArrowDown') {
    if (historyIndex < commandHistory.length - 1) {
      historyIndex++;
      e.target.value = commandHistory[historyIndex];
    } else {
      historyIndex = commandHistory.length;
      e.target.value = '';
    }
  }
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    appendTerminalLog(`[Clipboard] Copied '${text}' to clipboard.`, 'INFO');
  });
}

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str || '');
  return str.replace(/[&<>"']/g, match => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[match]);
}

// Initial fetch & setup
fetchTopology();
toggleAutoRefresh(true);
