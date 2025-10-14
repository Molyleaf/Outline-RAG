const avatar = document.getElementById('avatar');
const menu = document.getElementById('menu');
const chatEl = document.getElementById('chat');
const convsEl = document.getElementById('convs');
const newConvBtn = document.getElementById('newConv');
const sendBtn = document.getElementById('send');
const qEl = document.getElementById('q');
const refreshAll = document.getElementById('refreshAll');
const fileInput = document.getElementById('fileInput');
const streamToggle = document.getElementById('streamToggle');
const appRoot = document.querySelector('.app');
const hamburger = document.querySelector('.topbar .hamburger');
const sidebarVeil = document.querySelector('.sidebar-veil');
// 计算输入框最大高度（屏幕 20%）
let INPUT_MAX_PX = Math.floor(window.innerHeight * 0.2);
// 主题菜单项（系统/浅色/深色）
const themeRadios = Array.from(document.querySelectorAll('.menu .menu-radio'));

// --- 新增：模型定义与状态管理 ---
const MODELS = {
    'deepseek-ai/DeepSeek-V3.2-Exp': { name: 'Deepseek', icon: '/chat/static/img/DeepSeek.svg', temp: 0.7, top_p: 0.7 },
    'moonshotai/Kimi-K2-Instruct-0905': { name: 'Kimi K2', icon: '/chat/static/img/moonshotai_new.png', temp: 0.6, top_p: 0.7 },
    'zai-org/GLM-4.6': { name: 'ChatGLM', icon: '/chat/static/img/thudm.svg', temp: 0.6, top_p: 0.95 },
    'Qwen/Qwen3-Next-80B-A3B-Instruct': { name: 'Qwen3-Next', icon: '/chat/static/img/Tongyi.svg', temp: 0.6, top_p: 0.95 }
};
// 默认模型为列表第一个，或从 LocalStorage 读取
let currentModelId = localStorage.getItem('chat_model') || Object.keys(MODELS)[0];
if (!MODELS[currentModelId]) { // 如果存储的模型ID无效，则重置
    currentModelId = Object.keys(MODELS)[0];
    localStorage.setItem('chat_model', currentModelId);
}
let currentTemperature = MODELS[currentModelId].temp;
let currentTopP = MODELS[currentModelId].top_p;


// 根据模型名称返回头像 URL 的辅助函数 ---
function getAvatarUrlForModel(m) {
    const defaultAvatar = '/chat/static/img/openai.svg';
    if (!m) return defaultAvatar;
    const provider = (m.split('/')[0] || '').toLowerCase();

    if (provider === 'deepseek-ai') {
        return '/chat/static/img/DeepSeek.svg';
    } else if (provider === 'qwen') {
        return '/chat/static/img/Tongyi.svg';
    } else if (provider === 'moonshotai') {
        return '/chat/static/img/moonshotai_new.png';
    } else if (provider === 'zai-org' || provider === 'thudm') { // 兼容
        return '/chat/static/img/thudm.svg';
    } else if (provider === 'thudm') {
        return '/chat/static/img/thudm.svg';
    } else if (provider === 'inclusionAI') {
        return '/chat/static/img/ling.png';
    } else {
        return defaultAvatar;
    }
}

let currentConvId = null;
// 尝试从 URL /chat/<guid> 解析当前会话（与后端返回的 url 对齐）
(function initConvIdFromUrl() {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    if (m) currentConvId = m[1];
})();
let userInfo = null;

/** Material 风格弹窗与通知（替换 alert/confirm/prompt） */
function toast(message, variant = 'primary', timeout = 3000) {
    // 友好提示替换 alert
    const el = document.createElement('sl-alert');
    el.variant = variant; // 'primary' | 'success' | 'neutral' | 'warning' | 'danger'
    el.closable = true;
    el.innerHTML = `<sl-icon name="${variant === 'success' ? 'check2-circle' : variant === 'warning' ? 'exclamation-triangle' : variant === 'danger' ? 'x-octagon' : 'info-circle'}" slot="icon"></sl-icon>${message}`;
    document.body.appendChild(el);
    // 兼容：若 Shoelace 组件尚未注册，降级为直接打开
    if (typeof el.toast === 'function') {
        el.toast();
    } else {
        el.setAttribute('open', '');
    }
    if (timeout) {
        setTimeout(() => {
            if (typeof el.hide === 'function') el.hide(); else el.remove();
        }, timeout);
    }
    return el;
}

function confirmDialog(message, { okText = '确定', cancelText = '取消' } = {}) {
    return new Promise(resolve => {
        const dlg = document.createElement('sl-dialog');
        dlg.label = '请确认';
        dlg.innerHTML = `<div style="line-height:1.6">${message}</div>
        <div slot="footer" style="display:flex;gap:8px;justify-content:flex-end">
            <sl-button class="cancel" variant="neutral">${cancelText}</sl-button>
            <sl-button class="ok" variant="primary">${okText}</sl-button>
        </div>`;
        document.body.appendChild(dlg);

        // 创建一个健壮的隐藏对话框的辅助函数
        const hideDialog = () => {
            if (typeof dlg.hide === 'function') {
                dlg.hide();
            } else {
                dlg.removeAttribute('open');
            }
        };

        dlg.addEventListener('sl-after-hide', () => dlg.remove());
        dlg.querySelector('.cancel').addEventListener('click', () => { hideDialog(); resolve(false); });
        dlg.querySelector('.ok').addEventListener('click', () => { hideDialog(); resolve(true); });

        // 使用健壮的方式显示对话框
        if (typeof dlg.show === 'function') {
            dlg.show();
        } else {
            dlg.setAttribute('open', '');
        }
    });
}

function promptDialog(title, defaultValue = '', { okText = '确定', cancelText = '取消', placeholder = '' } = {}) {
    return new Promise(resolve => {
        const dlg = document.createElement('sl-dialog');
        dlg.label = title || '输入';
        dlg.innerHTML = `
          <sl-input value="${defaultValue.replace(/"/g, '&quot;')}" placeholder="${placeholder.replace(/"/g, '&quot;')}"></sl-input>
          <div slot="footer" style="display:flex;gap:8px;justify-content:flex-end">
            <sl-button class="cancel" variant="neutral">${cancelText}</sl-button>
            <sl-button class="ok" variant="primary">${okText}</sl-button>
          </div>`;
        document.body.appendChild(dlg);
        const input = dlg.querySelector('sl-input');

        // 创建一个健壮的隐藏对话框的辅助函数
        const hideDialog = () => {
            if (typeof dlg.hide === 'function') {
                dlg.hide();
            } else {
                dlg.removeAttribute('open');
            }
        };

        function done(val) { hideDialog(); resolve(val); }
        dlg.addEventListener('sl-after-hide', () => dlg.remove());
        dlg.querySelector('.cancel').addEventListener('click', () => done(null));
        dlg.querySelector('.ok').addEventListener('click', () => done(input.value.trim()));
        dlg.addEventListener('sl-initial-focus', () => input.focus());

        // 使用健壮的方式显示对话框
        if (typeof dlg.show === 'function') {
            dlg.show();
        } else {
            dlg.setAttribute('open', '');
        }
    });
}

/** Markdown 渲染与代码高亮 */
function renderMarkdown(md) {
    if (!window.marked) {
        // 回退：纯文本
        const pre = document.createElement('pre');
        pre.textContent = md || '';
        return pre;
    }
    const html = marked.parse(md || '', { breaks: true, gfm: true });
    const wrapper = document.createElement('div');
    wrapper.className = 'md-body';
    // 由 CSS 统一管理换行与折行
    wrapper.removeAttribute('style');
    wrapper.innerHTML = html;
    if (window.hljs) {
        wrapper.querySelectorAll('pre code').forEach(block => window.hljs.highlightElement(block));
    }
    return wrapper;
}

/** 打字机/进入过渡动画 */
function animateIn(el) {
    el.animate([{ transform: 'translateY(6px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }], {
        duration: 160,
        easing: 'cubic-bezier(.2,.8,.2,1)'
    });
}

avatar.addEventListener('click', () => {
    menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
});
// 初始化主题菜单选中态 + 点击切换保存
(function initThemeMenu(){
    const saved = localStorage.getItem('theme') || 'system';
    function applyActive() {
        themeRadios.forEach(r => {
            r.classList.toggle('active', r.dataset.theme === (localStorage.getItem('theme') || 'system'));
        });
    }
    // 应用到根节点
    document.documentElement.setAttribute('data-theme', (saved === 'light' || saved === 'dark') ? saved : 'system');
    applyActive();
    themeRadios.forEach(r => {
        r.addEventListener('click', (e) => {
            const t = r.dataset.theme;
            localStorage.setItem('theme', t);
            document.documentElement.setAttribute('data-theme', (t === 'light' || t === 'dark') ? t : 'system');
            applyActive();
            toast(`已切换为${t === 'system' ? '系统' : t === 'light' ? '浅色' : '深色'}主题`, 'success', 1800);
            menu.style.display = 'none';
        });
    });
})();

// 自动增高：输入框随输入自适应，最高为屏幕高度的 20%
(function initAutoResize() {
    function applyMax() {
        INPUT_MAX_PX = Math.floor(window.innerHeight * 0.2);
        qEl.style.maxHeight = INPUT_MAX_PX + 'px';
    }
    function autoresize() {
        // 先重置高度以便计算 scrollHeight
        qEl.style.height = 'auto';
        // 在最大高度限制内自适应
        const next = Math.min(qEl.scrollHeight, INPUT_MAX_PX);
        qEl.style.height = next + 'px';
        // 当达到上限时允许滚动，未达上限时不出现滚动条
        qEl.style.overflowY = (qEl.scrollHeight > INPUT_MAX_PX) ? 'auto' : 'hidden';
    }
    applyMax();
    // 初始一次（比如有占位文本或默认值时）
    autoresize();
    // 事件绑定
    qEl.addEventListener('input', autoresize);
    // 窗口尺寸变化时更新上限并重新计算
    window.addEventListener('resize', () => { applyMax(); autoresize(); });
})();

document.addEventListener('click', (e) => {
    if (!avatar.contains(e.target) && !menu.contains(e.target)) menu.style.display = 'none';
});
refreshAll.addEventListener('click', async (e) => {
    e.preventDefault();
    const r = await api('/chat/update/all', {method: 'POST'});

    if (r && r.ok) {
        toast('已开始全量刷新', 'primary', 2500);
        const poll = setInterval(async () => {
            const data = await api('/chat/api/refresh/status');
            if (!data) { // api() 返回 null 代表网络或认证失败
                clearInterval(poll);
                return;
            }
            if (data.status === 'success') {
                clearInterval(poll);
                toast(data.message || '全量刷新完成', 'success', 4000);
                console.log('全量刷新完成:', data.message);
            } else if (data.status === 'error') {
                clearInterval(poll);
                toast(data.message || '刷新失败', 'danger');
                console.error('全量刷新失败:', data.message);
            }
            // 若状态是 'running' 或 'idle'，则继续轮询
        }, 3000);
    } else if (r && r.error) {
        toast(r.error, 'warning');
    } else {
        toast('启动刷新失败', 'danger');
    }
});
fileInput.addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const form = new FormData();
    form.append('file', f);
    const res = await fetch('/chat/api/upload', { method: 'POST', body: form, credentials: 'include' });
    if (res.ok) toast('上传成功，已加入索引', 'success'); else toast('上传失败', 'danger');
    e.target.value = '';
});

// 4. 修复重命名与删除（确保请求头与响应判定更稳健）
async function api(path, opts) {
    const init = { credentials: 'include', ...(opts || {}) };
    init.headers = { 'Content-Type': 'application/json', ...(opts && opts.headers || {}) };
    const res = await fetch(path, init);
    if (res.status === 401) { window.location = '/chat/login'; return null; }
    if ((opts && opts.stream) || res.headers.get('content-type')?.includes('text/event-stream')) {
        return res;
    }
    // 尝试解析 json；失败返回空对象，便于后续判定
    try { return await res.json(); } catch { return { httpOk: res.ok }; }
}

async function loadUser() {
    const u = await api('/chat/api/me');
    if (!u) return;
    userInfo = u;
    // 主界面右上角仍显示用户头像
    avatar.style.backgroundImage = `url('${u.avatar_url || ''}')`;

    // 仅显示“你好”或“你好，{用户名}！”
    const greetTitle = document.querySelector('#greeting .greet-title');
    if (greetTitle) {
        const name = (u.name || u.username || '').trim();
        greetTitle.textContent = name ? `你好，${name}！` : '你好！';
    }
}

function toSameOriginUrl(c) {
    // 优先后端提供的 url；若为绝对地址且同源则直接用，否则回退到 /chat/<id>
    if (c?.url) {
        try {
            const u = new URL(c.url, location.origin);
            if (u.origin === location.origin && u.pathname.startsWith('/chat/')) {
                return u.href;
            }
        } catch (_) {}
    }
    return c?.id ? `${location.origin}/chat/${c.id}` : null;
}

async function loadConvs() {
    // 若用户信息未加载，先尝试一次，确保会话接口的鉴权上下文与头像渲染
    if (!userInfo) {
        try { await loadUser(); } catch(_) {}
    }
    const data = await api('/chat/api/conversations');
    convsEl.innerHTML = '';
    const list = data?.items || [];
    list.forEach(c => {
        const row = document.createElement('div');
        row.className = 'conv' + (String(c.id) === String(currentConvId) ? ' active' : '');
        row.tabIndex = 0;
        const titleEl = document.createElement('span');
        titleEl.className = 'conv-title';
        titleEl.textContent = c.title || ('会话 ' + (c.id || '').slice(0,8));

        const menuBtn = document.createElement('button');
        menuBtn.className = 'conv-menu';
        menuBtn.textContent = '⋯';

        const rowMenu = document.createElement('div');
        rowMenu.className = 'conv-menu-pop';
        const rename = document.createElement('div');
        rename.textContent = '重命名';
        const del = document.createElement('div');
        del.textContent = '删除';

        function go() {
            const href = toSameOriginUrl(c);
            if (href) location.href = href;
        }
        row.addEventListener('click', (e) => {
            if (menuBtn.contains(e.target) || rowMenu.contains(e.target)) return;
            go();
        });
        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                go();
            }
        });
        titleEl.onclick = (e) => { e.stopPropagation(); go(); };
        menuBtn.onclick = (e) => {
            e.stopPropagation();
            rowMenu.style.display = (rowMenu.style.display === 'block') ? 'none' : 'block';
        };

        rename.onclick = async (e) => {
            e.stopPropagation();
            const val = await promptDialog('重命名会话', titleEl.textContent, { placeholder: '请输入新标题' });
            if (val == null) { rowMenu.style.display = 'none'; return; }
            const t = val.trim();
            if (!t) { toast('标题不能为空', 'warning'); return; }
            // 改为使用 POST /chat/api/conversations/<id>/rename
            const res = await api(`/chat/api/conversations/${c.id}/rename`, {
                method: 'POST',
                body: JSON.stringify({ title: t })
            });
            const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
            if (success) {
                await loadConvs();
                toast('已重命名', 'success');
            } else {
                toast(res?.error || '重命名失败', 'danger');
            }
            rowMenu.style.display = 'none';
        };
        del.onclick = async (e) => {
            e.stopPropagation();
            const ok = await confirmDialog('确定删除该会话？此操作不可恢复。', { okText: '删除', cancelText: '取消' });
            if (!ok) { rowMenu.style.display = 'none'; return; }
            // 改为使用 POST /chat/api/conversations/<id>/delete
            const res = await api(`/chat/api/conversations/${c.id}/delete`, { method: 'POST' });
            const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
            if (success) {
                if (String(currentConvId) === String(c.id)) {
                    currentConvId = null; chatEl.innerHTML = '';
                    try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                }
                await loadConvs();
                toast('已删除', 'success');
            } else {
                toast(res?.error || '删除失败', 'danger');
            }
            rowMenu.style.display = 'none';
        };

        rowMenu.appendChild(rename);
        rowMenu.appendChild(del);
        rowMenu.style.display = 'none';

        if (!document.__convMenuCloserBound__) {
            document.addEventListener('click', (e) => {
                const pops = document.querySelectorAll('.conv-menu-pop');
                pops.forEach(pop => {
                    const parent = pop.parentElement;
                    const btn = parent?.querySelector('.conv-menu');
                    if (pop.style.display === 'block' && !pop.contains(e.target) && e.target !== btn) {
                        pop.style.display = 'none';
                    }
                });
            });
            document.__convMenuCloserBound__ = true;
        }

        row.appendChild(titleEl);
        row.appendChild(menuBtn);
        row.appendChild(rowMenu);
        convsEl.appendChild(row);
        animateIn(row);
    });
}

async function loadMessages() {
    chatEl.innerHTML = '';
    if (!currentConvId) return;
    const res = await api('/chat/api/messages?conv_id=' + currentConvId);
    const msgs = res?.items || [];
    // 有历史消息则隐藏问候语
    const greet = document.getElementById('greeting');
    if (greet) {
        greet.style.display = msgs.length ? 'none' : 'block';
    }
    msgs.forEach(m => appendMsg(m.role, m.content, m));
    chatEl.scrollTop = chatEl.scrollHeight;
}

function appendMsg(role, text, metadata = {}) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;

    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        const avatarUrl = getAvatarUrlForModel(metadata.model);
        avatarEl.style.backgroundImage = `url('${avatarUrl}')`;
    } else {
        avatarEl.style.display = 'none';
    }

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    const bubbleInner = document.createElement('div');
    bubbleInner.className = 'bubble-inner';

    const node = renderMarkdown(String(text ?? ''));
    bubbleInner.appendChild(node);
    bubble.appendChild(bubbleInner);

    // --- 新增：显示 AI 回复的元数据 ---
    if (role === 'assistant' && (metadata.model || metadata.temperature !== undefined)) {
        const metaEl = document.createElement('div');
        metaEl.className = 'msg-meta';
        const modelInfo = MODELS[metadata.model] || {};
        const modelName = modelInfo.name || (metadata.model || 'N/A').split('/')[1];
        const temp = typeof metadata.temperature === 'number' ? metadata.temperature.toFixed(2) : 'N/A';
        const topP = typeof metadata.top_p === 'number' ? metadata.top_p.toFixed(2) : 'N/A';
        const time = metadata.created_at ? new Date(metadata.created_at).toLocaleString() : '';

        let metaText = `模型: ${modelName} · Temp: ${temp} · Top-P: ${topP}`;
        if (time) metaText += ` · ${time}`;

        metaEl.textContent = metaText;
        // 放在 bubble-inner 外部，气泡的下方
        bubble.appendChild(metaEl);
    }

    if (role === 'user') {
        div.appendChild(document.createElement('div')); // 占位
        div.appendChild(bubble);
    } else {
        div.appendChild(avatarEl);
        div.appendChild(bubble);
    }

    chatEl.appendChild(div);
    animateIn(div);
    chatEl.scrollTop = chatEl.scrollHeight;
    return div;
}


// “新建对话”仅跳转到 /chat，不创建 ID；等待首次发送时再创建并替换 URL
newConvBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    // 清空当前对话上下文与消息区
    currentConvId = null;
    chatEl.innerHTML = '';
    // 确保问候语节点存在则插回去再显示（避免被清空后无法展示）
    let greet = document.getElementById('greeting');
    if (!greet) {
        greet = document.createElement('div');
        greet.id = 'greeting';
        greet.className = 'greeting';
        greet.innerHTML = `
            <div class="greet-title">你好！</div>
            <div class="greet-sub">随时提问，或从以下示例开始</div>
            <div class="greet-suggestions">
                <button class="chip">总结新手教程</button>
                <button class="chip">拉汶帝国完蛋了吗</button>
                <button class="chip">开发组的烂摊子怎么样了</button>
            </div>
        `;
        chatEl.appendChild(greet);
        // 绑定示例 chip 点击
        greet.querySelectorAll('.greet-suggestions .chip').forEach(btn => {
            btn.addEventListener('click', () => {
                qEl.value = btn.textContent.trim();
                qEl.focus();
            });
        });
    }
    // 若已有 userInfo，立即填充用户名
    const greetTitle = greet.querySelector('.greet-title');
    if (greetTitle) {
        const name = (userInfo?.name || userInfo?.username || '').trim();
        greetTitle.textContent = name ? `你好，${name}！` : '你好！';
    }
    greet.style.display = 'block';

    // 使用 History API 保持在 /chat
    try { history.pushState(null, '', '/chat'); } catch (_) { location.href = '/chat'; return; }

    // 窄屏下新建完成后自动关闭侧边栏
    if (window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});

// 监听浏览器前进后退，保持 currentConvId 与视图同步（pjax 式体验）
window.addEventListener('popstate', () => {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    currentConvId = m ? m[1] : null;
    chatEl.innerHTML = '';
    // 无会话则显示问候语
    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = currentConvId ? 'none' : 'block';
    // 有会话则异步加载消息
    if (currentConvId) loadMessages();
});

sendBtn.addEventListener('click', sendQuestion);
qEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuestion();
    }
});

async function sendQuestion() {
    const text = qEl.value.trim();
    if (!text) return;

    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = 'none';

    qEl.value = '';
    const ev = new Event('input');
    qEl.dispatchEvent(ev);

    if (!currentConvId) {
        const c = await api('/chat/api/conversations', {method:'POST', body: JSON.stringify({title: text.slice(0,30) || '新会话'})});
        const newId = c?.id;
        const newUrl = (c?.url && c.url.startsWith('/')) ? c.url : (newId ? ('/chat/' + newId) : null);
        if (!newId || !newUrl) {
            toast('创建会话失败', 'danger');
            return;
        }
        currentConvId = newId;
        try { history.replaceState(null, '', newUrl); } catch(_) { location.href = newUrl; return; }
        try { await loadConvs(); } catch(_) {}
    }

    appendMsg('user', text);
    qEl.value = '';

    const placeholderDiv = appendMsg('assistant', '', {
        model: currentModelId,
        temperature: currentTemperature,
        top_p: currentTopP
    });
    let placeholderContentRef = placeholderDiv.querySelector('.md-body');
    if (!placeholderContentRef) {
        const bubbleInner = placeholderDiv.querySelector('.bubble-inner') || placeholderDiv.querySelector('.bubble') || placeholderDiv;
        const newBody = document.createElement('div');
        newBody.className = 'md-body';
        bubbleInner.appendChild(newBody);
        placeholderContentRef = newBody;
    }
    placeholderContentRef.innerHTML = '▍'; // 初始光标

    let acc = '';

    const rerender = (isFinal = false) => {
        placeholderContentRef.innerHTML = marked.parse(acc + (!isFinal ? '▍' : ''), { breaks: true, gfm: true });
        if (isFinal && window.hljs) {
            placeholderContentRef.querySelectorAll('pre code').forEach(block => {
                try {
                    window.hljs.highlightElement(block);
                } catch (e) {
                    console.error("Highlight.js error:", e);
                }
            });
        }
        chatEl.scrollTop = chatEl.scrollHeight;
    };

    const res = await fetch('/chat/api/ask', {
        method: 'POST',
        body: JSON.stringify({
            conv_id: currentConvId,
            query: text,
            model: currentModelId,
            temperature: currentTemperature,
            top_p: currentTopP
        }),
        headers: {'Content-Type':'application/json'},
        credentials: 'include'
    });

    if (!res.ok) {
        placeholderContentRef.textContent = '请求失败';
        toast('请求失败', 'danger');
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let modelDetected = false;

    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true});
            let idx;
            while ((idx = buffer.indexOf('\n\n')) >= 0) {
                const chunk = buffer.slice(0, idx).trim();
                buffer = buffer.slice(idx + 2);
                if (chunk.startsWith('data:')) {
                    const data = chunk.slice(5).trim();
                    if (data === '[DONE]') {
                        rerender(true);
                        return;
                    }
                    try {
                        const j = JSON.parse(data);
                        if (!modelDetected && j.model) {
                            const avatarUrl = getAvatarUrlForModel(j.model);
                            const avatarEl = placeholderDiv.querySelector('.avatar');
                            if (avatarEl) {
                                avatarEl.style.backgroundImage = `url('${avatarUrl}')`;
                            }
                            modelDetected = true;
                        }

                        const delta = j.choices?.[0]?.delta?.content;
                        if (typeof delta === 'string' && delta.length > 0) {
                            acc += delta;
                            rerender(false);
                        }
                    } catch {}
                }
            }
        }
        rerender(true);
    } catch (e) {
        console.error("Stream processing error:", e);
        toast('连接中断', 'warning');
    }
}

(async function init() {
    // --- 适配新HTML：设置顶部操作栏 ---
    function setupTopbarActions() {
        const actionsContainer = document.querySelector('.topbar .actions');
        if (!actionsContainer) return;

        const uploadLabel = actionsContainer.querySelector('label.upload');
        const uploadSpan = uploadLabel ? uploadLabel.querySelector('span.btn') : null;
        if (uploadSpan) {
            uploadSpan.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>`;
            uploadSpan.style.width = '40px';
            uploadSpan.style.height = '40px';
            uploadSpan.style.borderRadius = '50%';
            uploadSpan.style.padding = '0';
            uploadSpan.style.display = 'inline-flex';
            uploadSpan.style.alignItems = 'center';
            uploadSpan.style.justifyContent = 'center';
        }

        // 创建新按钮和弹窗
        const modelBtn = document.createElement('button');
        modelBtn.className = 'btn tonal';
        modelBtn.innerHTML = `<img src="${MODELS[currentModelId].icon}" style="width:38px;height:38px;border-radius:50%;background-color: white;padding: 3px;">`;
        const tempBtn = document.createElement('button');
        tempBtn.className = 'btn tonal';
        tempBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"><path fill="currentColor" d="M12 13.25a3.25 3.25 0 1 0 0-6.5a3.25 3.25 0 0 0 0 6.5M13.5 4.636a.75.75 0 0 1-.75.75a4.75 4.75 0 0 0 0 9.228a.75.75 0 0 1 0 1.5a6.25 6.25 0 0 1 0-12.228a.75.75 0 0 1 .75.75M12 1.25a.75.75 0 0 1 .75.75v.255a.75.75 0 0 1-1.5 0V2a.75.75 0 0 1 .75-.75M12 20.25a.75.75 0 0 1 .75.75v.255a.75.75 0 0 1-1.5 0V21a.75.75 0 0 1 .75-.75m-6.79-2.54a.75.75 0 1 1-1.06-1.06l.176-.177a.75.75 0 0 1 1.06 1.06zm12.52 0a.75.75 0 1 1 1.06 1.06l-.176.177a.75.75 0 0 1-1.06-1.06z"/></svg>`;
        tempBtn.title = `Temperature: ${currentTemperature}`;

        const topPBtn = document.createElement('button');
        topPBtn.className = 'btn tonal';
        topPBtn.innerHTML = `<b>P</b>`;
        topPBtn.title = `Top-P: ${currentTopP}`;

        [modelBtn, tempBtn, topPBtn].forEach(btn => {
            btn.style.width = '40px';
            btn.style.height = '40px';
            btn.style.borderRadius = '50%';
            btn.style.padding = '0';
        });

        // 插入新按钮到上传按钮之前
        if (uploadLabel) {
            actionsContainer.insertBefore(modelBtn, uploadLabel);
            actionsContainer.insertBefore(tempBtn, uploadLabel);
            actionsContainer.insertBefore(topPBtn, uploadLabel);
        }

        // 弹窗逻辑
        function createPopover(btn, contentHtml, onOpen) {
            const pop = document.createElement('div');
            pop.className = 'toolbar-popover';
            pop.innerHTML = contentHtml;
            document.body.appendChild(pop);

            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const allPops = document.querySelectorAll('.toolbar-popover');
                const wasOpen = pop.style.display === 'block';

                // 先隐藏所有弹窗
                allPops.forEach(p => { p.style.display = 'none'; });

                // 如果当前弹窗不是打开状态，则显示它
                if (!wasOpen) {
                    const rect = btn.getBoundingClientRect();
                    // 定位在触发按钮的下方，并对齐右侧
                    pop.style.top = rect.bottom + 8 + 'px';
                    pop.style.left = 'auto';
                    pop.style.right = `${window.innerWidth - rect.right}px`;
                    pop.style.transform = ''; // 确保没有遗留的 transform

                    pop.style.display = 'block';
                    if (onOpen) onOpen(pop);
                }
            });
            return pop;
        }

        const modelMenuHtml = `<div class="model-menu">${Object.entries(MODELS).map(([id, m]) =>
            `<div class="model-item" data-id="${id}">
                <img src="${m.icon}"><span>${m.name}</span>
            </div>`).join('')}</div>`;
        const modelPop = createPopover(modelBtn, modelMenuHtml);

        const paramSliderHtml = (label, value, max, step) => `
            <div class="param-slider">
                <label><span>${label}</span><input type="number" class="param-input" value="${value}" step="${step}" max="${max}"></label>
                <input type="range" class="param-range" value="${value}" min="0" max="${max}" step="${step}">
            </div>`;
        const tempPop = createPopover(tempBtn, paramSliderHtml('Temperature', currentTemperature, 2, 0.05), (pop) => {
            pop.querySelector('.param-input').value = currentTemperature.toFixed(2);
            pop.querySelector('.param-range').value = currentTemperature;
        });
        const topPPop = createPopover(topPBtn, paramSliderHtml('Top-P', currentTopP, 2, 0.05), (pop) => {
            pop.querySelector('.param-input').value = currentTopP.toFixed(2);
            pop.querySelector('.param-range').value = currentTopP;
        });

        modelPop.querySelectorAll('.model-item').forEach(item => {
            item.addEventListener('click', () => {
                currentModelId = item.dataset.id;
                localStorage.setItem('chat_model', currentModelId);
                const modelConf = MODELS[currentModelId];
                currentTemperature = modelConf.temp;
                currentTopP = modelConf.top_p;
                modelBtn.innerHTML = `<img src="${modelConf.icon}" style="width:38px;height:38px;border-radius:50%;background-color: white;padding: 3px;">`;
                tempBtn.title = `Temperature: ${currentTemperature}`;
                topPBtn.title = `Top-P: ${currentTopP}`;
                modelPop.style.display = 'none';
            });
        });

        function setupSlider(pop, stateUpdater, btn, titlePrefix) {
            const input = pop.querySelector('.param-input');
            const range = pop.querySelector('.param-range');
            const update = (val) => {
                const num = parseFloat(val);
                if (!isNaN(num)) {
                    stateUpdater(num);
                    input.value = num.toFixed(2);
                    range.value = num;
                    btn.title = `${titlePrefix}: ${num.toFixed(2)}`;
                }
            };
            input.addEventListener('input', (e) => update(e.target.value));
            range.addEventListener('input', (e) => update(e.target.value));
        }

        setupSlider(tempPop, (val) => currentTemperature = val, tempBtn, 'Temperature');
        setupSlider(topPPop, (val) => currentTopP = val, topPBtn, 'Top-P');

        document.addEventListener('click', () => {
            document.querySelectorAll('.toolbar-popover').forEach(p => p.style.display = 'none');
        });

        // 注入CSS
        const styles = `
            .toolbar-popover { position: fixed; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius-m); box-shadow: var(--shadow-2); padding: 8px; z-index: 100; display: none; }
            .model-menu { display: flex; flex-direction: column; gap: 4px; }
            .model-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: var(--radius-s); cursor: pointer; white-space: nowrap; }
            .model-item:hover { background: color-mix(in srgb, var(--panel) 70%, var(--bg)); }
            .model-item img { width: 24px; height: 24px; border-radius: 4px; }
            .param-slider { padding: 8px; display: flex; flex-direction: column; gap: 8px; width: 220px; }
            .param-slider label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; color: var(--muted); }
            .param-input { width: 60px; border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 6px; padding: 4px 6px; font-size: 14px; }
            .param-range { width: 100%; accent-color: var(--accent); }
            .msg .bubble .msg-meta { font-size: 0.8rem; color: var(--muted); margin-top: 8px; }
        `;
        const styleSheet = document.createElement("style");
        styleSheet.innerText = styles;
        document.head.appendChild(styleSheet);
    }

    setupTopbarActions();

    // 顺序：先获取用户，再会话；完成后若有当前会话再加载消息
    (async () => {
        try { await loadUser(); } catch(_) {}
        await loadConvs();
        // 无会话 ID 时确保问候语显示（包括直接打开 /chat 或新建对话后）
        const greet = document.getElementById('greeting');
        if (!currentConvId && greet) {
            greet.style.display = 'block';
        }
        if (currentConvId) {
            try { await loadMessages(); } catch(_) {}
        }
    })();
})();

// 3. 修复移动端点击按钮不打开侧边栏问题（显式注册开关与遮罩关闭）
if (hamburger) {
    hamburger.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        appRoot?.classList.toggle('sidebar-open');
    });
}
if (sidebarVeil) {
    sidebarVeil.addEventListener('click', () => {
        appRoot?.classList.remove('sidebar-open');
    });
}
// 在窄屏导航到会话后自动关闭侧栏
convsEl.addEventListener('click', () => {
    if (window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});