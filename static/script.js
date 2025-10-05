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

// --- 新增: 根据模型名称返回头像 URL 的辅助函数 ---
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
    } else if (provider === 'zai-org') {
        return '/chat/static/img/zhipu.svg';
    } else if (provider === 'THUDM') {
        return '/chat/static/img/thudm.svg';
    } else if (provider === 'inclusionAI') {
        return '/chat/static/img/ling.png';
    } else {
        return defaultAvatar;
    }
}

// --- 移除: 旧的、基于全局变量的头像初始化逻辑 ---
// (function initAssistantAvatar() { ... })();

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
    // --- 修改: 传入 model ---
    msgs.forEach(m => appendMsg(m.role, m.content, m.model));
    chatEl.scrollTop = chatEl.scrollHeight;
}

// --- 修改: 增加 model 参数 ---
function appendMsg(role, text, model = null) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;

    // 左/右侧头像
    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        // --- 修改: 根据 model 动态设置头像 ---
        const avatarUrl = getAvatarUrlForModel(model);
        avatarEl.style.backgroundImage = `url('${avatarUrl}')`;
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

    const placeholderDiv = appendMsg('assistant', '');
    let placeholderContentRef = placeholderDiv.querySelector('.md-body');
    // 如果 appendMsg 未能创建 .md-body (例如在无 marked.js 的情况下)，确保它存在
    if (!placeholderContentRef) {
        const bubbleInner = placeholderDiv.querySelector('.bubble-inner') || placeholderDiv.querySelector('.bubble') || placeholderDiv;
        const newBody = document.createElement('div');
        newBody.className = 'md-body';
        bubbleInner.appendChild(newBody);
        placeholderContentRef = newBody;
    }

    let acc = '';

    // --- 修复开始: 简化并修正 rerender 逻辑 ---
    const rerender = (isFinal = false) => {
        // 直接更新 innerHTML，而不是替换节点，更简单且健壮
        placeholderContentRef.innerHTML = marked.parse(acc, { breaks: true, gfm: true });

        // 仅在最后一次渲染时执行代码高亮，提高性能
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
    // --- 修复结束 ---

    const res = await fetch('/chat/api/ask', {
        method: 'POST',
        body: JSON.stringify({conv_id: currentConvId, query: text}),
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
    let modelDetected = false; // --- 新增: 标记是否已检测到模型

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
                        rerender(true); // 传入 true 表示这是最后一次渲染
                        return;
                    }
                    try {
                        const j = JSON.parse(data);
                        // --- 新增: 实时更新头像 ---
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
                            rerender(false); // 实时渲染，不执行高亮
                        }
                    } catch {}
                }
            }
        }
        rerender(true); // 所有数据显示完后，执行最终渲染
    } catch (e) {
        console.error("Stream processing error:", e);
        toast('连接中断', 'warning');
    }
}

(async function init() {
    // 动态加载前端库（若页面未引入时）
    function ensureScript(src, type = 'text/javascript') {
        return new Promise((resolve) => {
            if ([...document.scripts].some(s => (s.src || '').includes(src))) return resolve();
            const s = document.createElement('script');
            if (type === 'module') s.type = 'module';
            s.src = src;
            s.onload = () => resolve();
            s.onerror = () => resolve(); // 不阻塞后续逻辑，避免因 CDN 波动导致初始化中断
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