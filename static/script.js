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
// 3. 移动端侧边栏开关元素
const appRoot = document.querySelector('.app');
const hamburger = document.querySelector('.topbar .hamburger');
const sidebarVeil = document.querySelector('.sidebar-veil');
let ASSISTANT_AVATAR_URL = '/chat/static/DeepSeek.svg'; // 将在运行时按 CHAT_MODEL 覆盖

// 主题菜单项（系统/浅色/深色）
const themeRadios = Array.from(document.querySelectorAll('.menu .menu-radio'));

// 按 CHAT_MODEL 选择 AI 头像与外发光
(function initAssistantAvatar() {
    const chatModel =
        (window.CHAT_MODEL || '') ||
        (document.querySelector('meta[name="chat-model"]')?.getAttribute('content') || '');
    const m = (chatModel || '').trim();

    const styleEl = document.createElement('style');
    styleEl.setAttribute('data-dynamic-style', 'assistant-avatar-glow');

    function glowCss(selector) {
        return `
            ${selector} .avatar {
                filter: drop-shadow(0 0 6px rgba(255,255,255,.9)) drop-shadow(0 0 16px rgba(255,255,255,.6));
            }
        `;
    }

    // 路径要求：
    let applyGlow = false;
    if (/^deepseek/i.test(m)) {
        ASSISTANT_AVATAR_URL = '/chat/static/DeepSeek.svg';
        applyGlow = true;
    } else if (/^(qwen|qwq)/i.test(m)) {
        ASSISTANT_AVATAR_URL = '/chat/static/Tongyi.svg';
        applyGlow = true;
    } else if (/^kimi/i.test(m)) {
        ASSISTANT_AVATAR_URL = '/chat/static/moonshotai_new.png';
        applyGlow = true;
    }

    if (applyGlow) {
        styleEl.textContent = glowCss('.msg.assistant');
        document.head.appendChild(styleEl);
    }
})();

let currentConvId = null;
// 尝试从 URL /chat/<guid> 解析当前会话（与后端返回的 url 对齐）
(function initConvIdFromUrl() {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    if (m) currentConvId = m[1];
})();
let userInfo = null;

/** Material 风格弹窗与通知（替换 alert/confirm/prompt） */
// 依赖：Shoelace Web Components（Material-like）与 snackbar 动画
// 在 index.html 中通过 CDN 引入：
// <script type="module" src="https://cdn.jsdelivr.net/npm/@shoelace-style/shoelace@2.15.0/cdn/shoelace-autoloader.js"></script>
// <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@shoelace-style/shoelace@2.15.0/cdn/themes/light.css" />
function toast(message, variant = 'primary', timeout = 3000) {
    // 友好提示替换 alert
    const el = document.createElement('sl-alert');
    el.variant = variant; // 'primary' | 'success' | 'neutral' | 'warning' | 'danger'
    el.closable = true;
    el.innerHTML = `<sl-icon name="${variant === 'success' ? 'check2-circle' : variant === 'warning' ? 'exclamation-triangle' : variant === 'danger' ? 'x-octagon' : 'info-circle'}" slot="icon"></sl-icon>${message}`;
    document.body.appendChild(el);
    el.toast();
    if (timeout) {
        setTimeout(() => el.hide(), timeout);
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
        dlg.addEventListener('sl-after-hide', () => dlg.remove());
        dlg.querySelector('.cancel').addEventListener('click', () => { dlg.hide(); resolve(false); });
        dlg.querySelector('.ok').addEventListener('click', () => { dlg.hide(); resolve(true); });
        dlg.show();
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
        function done(val) { dlg.hide(); resolve(val); }
        dlg.addEventListener('sl-after-hide', () => dlg.remove());
        dlg.querySelector('.cancel').addEventListener('click', () => done(null));
        dlg.querySelector('.ok').addEventListener('click', () => done(input.value.trim()));
        dlg.addEventListener('sl-initial-focus', () => input.focus());
        dlg.show();
    });
}

/** Markdown 渲染与代码高亮 */
// 依赖：marked + highlight.js（或 prism），通过 CDN 引入：
// <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
// 注意：浏览器环境请使用 UMD 版 highlight.min.js（非 common.min.js/common.js）
// <script src="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/highlight.min.js"></script>
// <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11.9.0/styles/github.min.css">
function renderMarkdown(md) {
    if (!window.marked) {
        // 回退：纯文本
        const pre = document.createElement('pre');
        pre.textContent = md || '';
        return pre;
    }
    const html = marked.parse(md || '', {
        breaks: true,
        gfm: true
    });
    const wrapper = document.createElement('div');
    wrapper.className = 'md-body';
    wrapper.innerHTML = html;
    if (window.hljs) {
        wrapper.querySelectorAll('pre code').forEach(block => {
            window.hljs.highlightElement(block);
        });
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

document.addEventListener('click', (e) => {
    if (!avatar.contains(e.target) && !menu.contains(e.target)) menu.style.display = 'none';
});
refreshAll.addEventListener('click', async (e) => {
    e.preventDefault();
    // 先提示“已开始全量刷新”
    toast('已开始全量刷新', 'primary', 2500);
    const r = await fetch('/chat/update/all', {method: 'POST', credentials: 'include'});
    if (r.status === 202) {
        // 后台异步刷新，前端不阻塞
        return;
    }
    if (r.ok) {
        toast('已完成全量刷新', 'success');
    } else {
        try {
            const j = await r.json();
            toast(j?.error || '刷新失败', 'danger');
        } catch {
            toast('刷新失败', 'danger');
        }
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
    msgs.forEach(m => appendMsg(m.role, m.content));
    chatEl.scrollTop = chatEl.scrollHeight;
}

function appendMsg(role, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;

    // 左/右侧头像
    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        avatarEl.style.backgroundImage = `url('${ASSISTANT_AVATAR_URL}')`;
    } else {
        // 取消显示用户消息内的头像
        avatarEl.style.display = 'none';
    }

    // 气泡容器
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    const bubbleInner = document.createElement('div');
    bubbleInner.className = 'bubble-inner';

    // 三边圆角：用户右上角方形；AI 左上角方形
    if (role === 'user') {
        bubbleInner.classList.add('bubble-user-corners');
    } else {
        bubbleInner.classList.add('bubble-ai-corners');
    }

    // Markdown 渲染
    const node = renderMarkdown(String(text ?? ''));
    bubbleInner.appendChild(node);
    bubble.appendChild(bubbleInner);

    // 组装
    if (role === 'user') {
        // 用户消息在右侧（不显示用户头像）
        div.appendChild(document.createElement('div')); // 占位，维持网格
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

newConvBtn.addEventListener('click', async () => {
    const c = await api('/chat/api/conversations', {method:'POST', body: JSON.stringify({title: '新会话'})});
    if (c?.url) { location.href = c.url; return; }
    if (c?.id) { location.href = '/chat/' + c.id; return; }
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

    // 一旦用户开始对话，隐藏问候语
    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = 'none';

    if (!currentConvId) {
        const c = await api('/chat/api/conversations', {method:'POST', body: JSON.stringify({title: text.slice(0,30)})});
        if (c?.url) { location.href = c.url; return; }
        if (c?.id) { location.href = '/chat/' + c.id; return; }
        return;
    }
    // 追加用户消息
    appendMsg('user', text);
    qEl.value = '';

    // 流式始终开启：不再依赖隐藏的开关节点
    const placeholderDiv = document.createElement('div');
    placeholderDiv.className = 'msg assistant';
    let placeholderContent = document.createElement('div');
    placeholderContent.className = 'md-body';
    placeholderContent.innerHTML = ''; // 将持续增量写入
    placeholderDiv.appendChild(placeholderContent);
    chatEl.appendChild(placeholderDiv);
    animateIn(placeholderDiv);
    chatEl.scrollTop = chatEl.scrollHeight;

    const res = await fetch('/chat/api/ask', { // 始终开启 SSE
        method: 'POST',
        body: JSON.stringify({conv_id: currentConvId, query: text}),
        headers: {'Content-Type':'application/json'},
        credentials: 'include'
    });

    if (!res.ok) {
        placeholderContent.textContent = '请求失败';
        toast('请求失败', 'danger');
        return;
    }

    // 流式解析 + 增量 markdown 渲染（简单策略：累积文本后按块渲染）
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let acc = '';
    let placeholderContentRef = placeholderContent;

    const rerender = () => {
        const tmp = renderMarkdown(acc);
        placeholderDiv.replaceChild(tmp, placeholderContentRef);
        placeholderContentRef = tmp;
        chatEl.scrollTop = chatEl.scrollHeight;
    };

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
                        rerender();
                        return;
                    }
                    try {
                        const j = JSON.parse(data);
                        if (j.delta) {
                            acc += j.delta;
                            // 到标点或换行时重渲染
                            if (/[。\.\n\r]$/.test(j.delta)) rerender();
                        }
                    } catch {}
                }
            }
        }
        rerender();
    } catch (_) {
        toast('连接中断', 'warning');
    }
}

(async function init(){
    // 动态加载前端库（若页面未引入时）
    function ensureScript(src, type = 'text/javascript') {
        return new Promise((resolve) => {
            if ([...document.scripts].some(s => (s.src || '').includes(src))) return resolve();
            const s = document.createElement('script');
            if (type === 'module') s.type = 'module';
            s.src = src;
            s.onload = () => resolve();
            document.head.appendChild(s);
        });
    }
    function ensureStyle(href) {
        if ([...document.styleSheets].some(ss => (ss.href || '').includes(href))) return;
        const l = document.createElement('link');
        l.rel = 'stylesheet';
        l.href = href;
        document.head.appendChild(l);
    }

    // Shoelace（弹窗/按钮/alert）
    await ensureScript('https://unpkg.shop.jd.com/@shoelace-style/shoelace/cdn/shoelace-autoloader.js', 'module');
    ensureStyle('https://unpkg.shop.jd.com/@shoelace-style/shoelace/cdn/themes/light.css');
    // marked + highlight
    await ensureScript('https://jsd.onmicrosoft.cn/npm/marked/marked.min.js');
    await ensureScript('https://jsd.onmicrosoft.cn/npm/highlight.js/highlight.min.js');
    ensureStyle('https://jsd.onmicrosoft.cn/npm/highlight.js/styles/github.min.css');

    await loadUser();
    await loadConvs();
    // 初次进入带 GUID 的地址时加载消息
    if (currentConvId) {
        await loadMessages();
    }
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