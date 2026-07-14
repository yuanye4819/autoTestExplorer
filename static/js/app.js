/**
 * AI Web 探索测试系统 — 前端应用
 * 管理 WebSocket 连接、步骤渲染、代码展示
 */

// ── 全局状态 ────────────────────────────────────────
const state = {
    currentTaskId: null,
    ws: null,
    steps: [],
    featureContent: '',
    scriptContent: '',
    pageObjectContent: '',
    executionLog: '',
    taskStatus: 'idle',
    activeTab: 'explore',
};

// ── DOM 引用 ────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    form: $('#task-form'),
    btnSubmit: $('#btn-submit'),
    btnRun: $('#btn-run'),
    statusBadge: $('#status-badge'),
    stepCount: $('#step-count'),
    stepsPanel: $('#steps-panel'),
    logArea: $('#log-area'),
    screenshotPanel: $('#screenshot-panel'),
    taskList: $('#task-list'),
    tabs: $$('.tab'),
    emptyExplore: $('#empty-explore'),
    emptyScreenshot: $('#empty-screenshot'),
};

// ── 初始化 ──────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadTaskList();
});

// ── 标签页 ──────────────────────────────────────────
function initTabs() {
    dom.tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            dom.tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            state.activeTab = tab.dataset.tab;

            $$('.tab-content').forEach(c => c.classList.remove('active'));
            const content = $(`#tab-${tab.dataset.tab}`);
            if (content) content.classList.add('active');
        });
    });
}

function switchTab(name) {
    const tab = document.querySelector(`.tab[data-tab="${name}"]`);
    if (tab) tab.click();
}

// ── 任务提交 ────────────────────────────────────────
async function submitTask(e) {
    e.preventDefault();

    const url = $('#input-url').value.trim();
    const requirements = $('#input-requirements').value.trim();
    const username = $('#input-username').value.trim();
    const password = $('#input-password').value.trim();
    const maxSteps = parseInt($('#input-max-steps').value) || 20;

    if (!url) return;

    dom.btnSubmit.disabled = true;
    dom.btnSubmit.textContent = '⏳ 提交中...';

    try {
        const resp = await fetch('/api/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_url: url,
                requirements,
                username: username || null,
                password: password || null,
                max_steps: maxSteps,
            }),
        });

        const task = await resp.json();
        state.currentTaskId = task.id;
        state.steps = [];
        state.featureContent = '';
        state.scriptContent = '';
        state.pageObjectContent = '';
        state.executionLog = '';
        state.taskStatus = 'pending';

        // 清空界面
        dom.stepsPanel.innerHTML = '';
        dom.logArea.textContent = '';
        dom.screenshotPanel.innerHTML = '';
        $('#code-feature').textContent = '探索中...';
        $('#code-script').textContent = '探索中...';
        $('#code-pageobject').textContent = '探索中...';
        $('#code-log').textContent = '等待执行...';
        dom.btnRun.disabled = true;
        dom.emptyExplore.style.display = 'none';
        dom.emptyScreenshot.style.display = 'none';

        // 显示状态
        updateStatusBadge('pending');
        dom.statusBadge.style.display = 'inline-block';

        // 连接 WebSocket
        connectWebSocket(task.id);

        // 刷新任务列表
        loadTaskList();

    } catch (err) {
        alert('创建任务失败: ' + err.message);
    } finally {
        dom.btnSubmit.disabled = false;
        dom.btnSubmit.textContent = '🚀 开始探索';
    }
}

// ── WebSocket ───────────────────────────────────────
function connectWebSocket(taskId) {
    if (state.ws) {
        state.ws.close();
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/${taskId}`;

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        addLog('🔗 WebSocket 已连接\n');
        updateStatusBadge('exploring');
    };

    state.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleWSMessage(msg);
    };

    state.ws.onerror = (err) => {
        addLog('❌ WebSocket 连接错误\n');
    };

    state.ws.onclose = () => {
        addLog('🔌 WebSocket 已断开\n');
    };
}

function handleWSMessage(msg) {
    const { type, data } = msg;

    switch (type) {
        case 'status':
            handleStatus(data);
            break;
        case 'step_update':
            handleStepUpdate(data);
            break;
        case 'reasoning':
            handleReasoning(data);
            break;
        case 'log':
            addLog(data.message + '\n');
            break;
        case 'snapshot':
            handleSnapshot(data);
            break;
        case 'error':
            addLog(`❌ 错误: ${data.message}\n`);
            updateStatusBadge('failed');
            break;
        case 'execution_complete':
            handleExecutionComplete(data);
            break;
    }
}

function handleStatus(data) {
    const status = data.status;
    let badgeStatus = 'exploring';

    if (status === 'exploration_done') badgeStatus = 'generating';
    else if (status === 'completed') badgeStatus = 'completed';
    else if (status === 'failed') badgeStatus = 'failed';

    updateStatusBadge(badgeStatus);

    if (data.step !== undefined) {
        dom.stepCount.style.display = 'inline-block';
        dom.stepCount.textContent = data.step;
    }
}

function handleStepUpdate(data) {
    const idx = data.index;
    const existing = document.getElementById(`step-${idx}`);

    // 隐藏空状态
    dom.emptyExplore.style.display = 'none';

    // 构建或更新步骤卡片
    const card = existing || createStepCard(data);
    if (!existing) {
        dom.stepsPanel.appendChild(card);
        dom.stepsPanel.scrollTop = dom.stepsPanel.scrollHeight;
    }

    // 更新状态样式
    card.className = `step-card step-${data.status}`;
    const statusEl = card.querySelector('.step-status');
    if (statusEl) {
        statusEl.textContent = {
            success: '✅', failed: '❌', running: '⏳', pending: '⏸', skipped: '⏭'
        }[data.status] || '';
    }

    // 更新截图
    if (data.screenshot_b64) {
        const img = card.querySelector('.step-screenshot');
        if (img) {
            img.src = `data:image/png;base64,${data.screenshot_b64}`;
            img.style.display = 'block';
        }
    }

    // 更新步骤计数
    dom.stepCount.style.display = 'inline-block';
    dom.stepCount.textContent = data.index + 1;

    // 存储步骤数据
    if (!state.steps.find(s => s.index === data.index)) {
        state.steps.push(data);
    } else {
        const existingStep = state.steps.find(s => s.index === data.index);
        Object.assign(existingStep, data);
    }
}

function createStepCard(data) {
    const card = document.createElement('div');
    card.id = `step-${data.index}`;
    card.className = 'step-card step-running';

    const actionClass = `action-${data.action}`;
    const actionLabel = {
        navigate: '🌐 导航', click: '👆 点击', fill: '⌨ 输入',
        select: '📋 选择', check: '☑ 勾选', hover: '🖱 悬停',
        wait: '⏳ 等待', assert_visible: '🔍 验证可见',
        assert_text: '📝 验证文本', assert_url: '🔗 验证URL',
        screenshot: '📸 截图'
    }[data.action] || data.action;

    card.innerHTML = `
        <div class="step-header">
            <span class="step-index">${data.index + 1}</span>
            <span class="step-action ${actionClass}">${actionLabel}</span>
            <span class="step-status">⏳</span>
        </div>
        <div class="step-desc">${escapeHtml(data.description || '')}</div>
        <div class="step-reasoning" style="display:${data.reasoning ? 'block' : 'none'}">💡 ${escapeHtml(data.reasoning || '')}</div>
        <div class="step-meta">
            <span>${data.duration_ms ? data.duration_ms + 'ms' : ''}</span>
            <span style="color:var(--error)">${escapeHtml(data.error || '')}</span>
        </div>
        <img class="step-screenshot" style="display:none;" alt="步骤截图">
    `;

    return card;
}

function handleReasoning(data) {
    addLog(`💡 [推理] ${data.reasoning || data.description}\n`);
}

function handleSnapshot(data) {
    // 更新截图面板
    dom.emptyScreenshot.style.display = 'none';
    if (data.screenshot) {
        dom.screenshotPanel.innerHTML = `
            <div style="margin-bottom:8px;color:var(--text2);font-size:12px;">
                📍 ${escapeHtml(data.url || '')} — ${escapeHtml(data.title || '')}
                (${data.element_count || 0} 个可交互元素)
            </div>
            <img src="data:image/png;base64,${data.screenshot}" alt="页面截图">
        `;
    }
}

function handleExecutionComplete(data) {
    if (data.passed) {
        addLog('\n✅ 测试全部通过！\n');
        updateStatusBadge('completed');
    } else {
        addLog('\n❌ 测试失败，请查看日志\n');
        updateStatusBadge('failed');
    }
    state.executionLog = data.log || '';
    $('#code-log').textContent = data.log || '';
    dom.btnRun.disabled = false;
    dom.btnRun.textContent = '▶ 运行脚本';
}

function addLog(text) {
    dom.logArea.textContent += text;
    dom.logArea.scrollTop = dom.logArea.scrollHeight;
}

function updateStatusBadge(status) {
    state.taskStatus = status;
    dom.statusBadge.style.display = 'inline-block';
    dom.statusBadge.className = `status-${status}`;
    dom.statusBadge.textContent = {
        pending: '⏸ 等待中',
        exploring: '🔍 探索中',
        generating: '⚙ 生成中',
        running: '▶ 执行中',
        completed: '✅ 完成',
        failed: '❌ 失败',
        cancelled: '🚫 已取消',
    }[status] || status;

    if (status === 'completed' || status === 'failed') {
        dom.btnSubmit.disabled = false;
        dom.btnSubmit.textContent = '🚀 开始探索';
        // 刷新任务详情
        loadTaskDetail(state.currentTaskId);
    }
}

// ── 任务列表 ────────────────────────────────────────
async function loadTaskList() {
    try {
        const resp = await fetch('/api/tasks');
        const tasks = await resp.json();
        renderTaskList(tasks);
    } catch (err) {
        console.error('加载任务列表失败:', err);
    }
}

function renderTaskList(tasks) {
    dom.taskList.innerHTML = tasks.slice(0, 20).map(t => `
        <div class="task-item ${t.id === state.currentTaskId ? 'active' : ''}"
             onclick="selectTask('${t.id}')">
            <div class="task-url">${escapeHtml(t.target_url)}</div>
            <div class="task-meta">
                <span>${t.step_count || 0} 步</span>
                <span class="status-${t.status}">${t.status}</span>
            </div>
            <div class="task-meta">
                <span>${formatTime(t.created_at)}</span>
                ${t.requirements ? `<span>${escapeHtml(t.requirements.substring(0, 20))}...</span>` : ''}
            </div>
        </div>
    `).join('') || '<div style="color:var(--text2);font-size:12px;">暂无任务</div>';
}

async function selectTask(taskId) {
    state.currentTaskId = taskId;
    connectWebSocket(taskId);
    await loadTaskDetail(taskId);
    loadTaskList();
}

async function loadTaskDetail(taskId) {
    try {
        const resp = await fetch(`/api/tasks/${taskId}`);
        const task = await resp.json();

        // 更新状态
        updateStatusBadge(task.status);
        dom.stepCount.textContent = task.steps?.length || 0;
        dom.stepCount.style.display = task.steps?.length ? 'inline-block' : 'none';

        // 渲染步骤
        if (task.steps) {
            dom.stepsPanel.innerHTML = '';
            dom.emptyExplore.style.display = task.steps.length ? 'none' : 'flex';
            task.steps.forEach(s => {
                const card = createStepCard(s);
                card.className = `step-card step-${s.status}`;
                const statusEl = card.querySelector('.step-status');
                if (statusEl) {
                    statusEl.textContent = {
                        success: '✅', failed: '❌', running: '⏳', pending: '⏸', skipped: '⏭'
                    }[s.status] || '';
                }
                if (s.screenshot_b64) {
                    const img = card.querySelector('.step-screenshot');
                    if (img) {
                        img.src = `data:image/png;base64,${s.screenshot_b64}`;
                        img.style.display = 'block';
                    }
                }
                dom.stepsPanel.appendChild(card);
            });
            state.steps = task.steps || [];
        }

        // 更新代码面板
        if (task.feature_content) {
            state.featureContent = task.feature_content;
            $('#code-feature').textContent = task.feature_content;
        }
        if (task.test_script) {
            state.scriptContent = task.test_script;
            $('#code-script').textContent = task.test_script;
            dom.btnRun.disabled = false;
        }
        if (task.page_object_code) {
            state.pageObjectContent = task.page_object_code;
            $('#code-pageobject').textContent = task.page_object_code;
        }
        if (task.execution_log) {
            state.executionLog = task.execution_log;
            $('#code-log').textContent = task.execution_log;
        }

    } catch (err) {
        console.error('加载任务详情失败:', err);
    }
}

// ── 运行测试 ────────────────────────────────────────
async function runTests() {
    if (!state.currentTaskId || !state.scriptContent) return;

    dom.btnRun.disabled = true;
    dom.btnRun.textContent = '⏳ 执行中...';
    $('#code-log').textContent = '正在执行测试脚本...\n';
    switchTab('log');
    updateStatusBadge('running');

    try {
        await fetch(`/api/tasks/${state.currentTaskId}/run`, { method: 'POST' });
    } catch (err) {
        $('#code-log').textContent = `执行失败: ${err.message}`;
        dom.btnRun.disabled = false;
        dom.btnRun.textContent = '▶ 运行脚本';
    }
}

// ── 复制代码 ────────────────────────────────────────
function copyCode(type) {
    let text = '';
    switch (type) {
        case 'feature': text = state.featureContent || $('#code-feature').textContent; break;
        case 'script': text = state.scriptContent || $('#code-script').textContent; break;
        case 'pageobject': text = state.pageObjectContent || $('#code-pageobject').textContent; break;
        case 'log': text = state.executionLog || $('#code-log').textContent; break;
    }
    navigator.clipboard.writeText(text).then(() => {
        alert('已复制到剪贴板！');
    });
}

// ── 工具函数 ────────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    return d.toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit',
    });
}
