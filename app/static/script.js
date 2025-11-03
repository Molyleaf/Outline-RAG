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

// --- (Req 1) 新增：自定义移动端底部弹窗 ---
const mobileSheetOverlay = document.createElement('div');
mobileSheetOverlay.className = 'mobile-sheet-overlay';
const mobileSheetPanel = document.createElement('div');
mobileSheetPanel.className = 'mobile-sheet-panel';
const mobileSheetHeader = document.createElement('div');
mobileSheetHeader.className = 'mobile-sheet-header';
const mobileSheetContent = document.createElement('div');
mobileSheetContent.className = 'mobile-sheet-content';
mobileSheetPanel.append(mobileSheetHeader, mobileSheetContent);
document.body.append(mobileSheetOverlay, mobileSheetPanel);

/** (Req 1) 显示自定义底部弹窗 */
function showMobileSheet(contentHtml, label = '') {
    mobileSheetHeader.textContent = label;
    mobileSheetHeader.style.display = label ? 'block' : 'none';
    mobileSheetContent.innerHTML = contentHtml;
    mobileSheetOverlay.classList.add('visible');
    mobileSheetPanel.classList.add('visible');
}
/** (Req 1) 隐藏自定义底部弹窗 */
function hideMobileSheet() {
    mobileSheetOverlay.classList.remove('visible');
    mobileSheetPanel.classList.remove('visible');
}
// (Req 3) 点击遮罩关闭
mobileSheetOverlay.addEventListener('click', hideMobileSheet);
// --- 结束 (Req 1) ---


// --- 新增：模型定义与状态管理 ---
const MODELS = {
    'deepseek-ai/DeepSeek-V3.2-Exp': { name: 'Deepseek', icon: '/chat/static/img/DeepSeek.svg', temp: 0.7, top_p: 0.7 },
    'moonshotai/Kimi-K2-Instruct-0905': { name: 'Kimi K2', icon: '/chat/static/img/moonshotai_new.png', temp: 0.6, top_p: 0.7 },
    'zai-org/GLM-4.6': { name: 'ChatGLM', icon: '/chat/static/img/thudm.svg', temp: 0.6, top_p: 0.95 },
    'Qwen/Qwen3-Next-80B-A3B-Instruct': { name: 'Qwen3-Next', icon: '/chat/static/img/Tongyi.svg', temp: 0.6, top_p: 0.95 },
    'inclusionAI/Ling-1T': { name:'Ling-1T', icon: '/chat/static/img/ling.png', temp: 0.6, top_p: 0.7 }
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
    } else if (provider === 'inclusionai') {
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
    // 等待 marked 加载完成
    if (typeof window.marked.parse !== 'function') {
        const pre = document.createElement('pre');
        pre.textContent = md || '(Markdown 渲染器加载中...)';
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
    // (Req 9) 改为 toggle class
    menu.classList.toggle('visible');
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
            // (Req 9) 改为 remove class
            menu.classList.remove('visible');
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
    // (Req 9) 改为 remove class
    if (!avatar.contains(e.target) && !menu.contains(e.target)) menu.classList.remove('visible');
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

        // (Req 3) 修改点击逻辑为 PJAX
        row.addEventListener('click', (e) => {
            if (menuBtn.contains(e.target) || rowMenu.contains(e.target)) return;

            e.preventDefault();
            const href = toSameOriginUrl(c);
            if (!href || href === location.href) return; // 已经是当前会话

            currentConvId = c.id;
            try {
                history.pushState(null, '', href);
            } catch(_) {
                location.href = href; // 回退到跳转
                return;
            }

            chatEl.innerHTML = '';
            document.getElementById('greeting')?.remove(); // 移除问候语
            loadMessages(); // 手动加载消息

            // 更新侧边栏高亮
            document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
            row.classList.add('active');
        });

        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                row.click(); // 触发上面修改过的 click 事件
            }
        });

        // titleEl.onclick = (e) => { e.stopPropagation(); go(); }; // 已被 row click 替代

        menuBtn.onclick = (e) => {
            e.stopPropagation();
            // (Req 5, 9) 改为 toggle class
            rowMenu.classList.toggle('visible');
        };

        rename.onclick = async (e) => {
            e.stopPropagation();
            const val = await promptDialog('重命名会话', titleEl.textContent, { placeholder: '请输入新标题' });
            // (Req 5, 9) 改为 remove class
            if (val == null) { rowMenu.classList.remove('visible'); return; }
            const t = val.trim();
            if (!t) { toast('标题不能为空', 'warning'); return; }
            // 改为使用 POST /chat/api/conversations/<id>/rename
            const res = await api(`/chat/api/conversations/${c.id}/rename`, {
                method: 'POST',
                body: JSON.stringify({ title: t })
            });
            const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
            if (success) {
                await loadConvs(); // 重新加载列表以更新标题
                toast('已重命名', 'success');
            } else {
                toast(res?.error || '重命名失败', 'danger');
            }
            // (Req 5, 9) 改为 remove class
            rowMenu.classList.remove('visible');
        };
        del.onclick = async (e) => {
            e.stopPropagation();
            const ok = await confirmDialog('确定删除该会话？此操作不可恢复。', { okText: '删除', cancelText: '取消' });
            // (Req 5, 9) 改为 remove class
            if (!ok) { rowMenu.classList.remove('visible'); return; }
            // 改为使用 POST /chat/api/conversations/<id>/delete
            const res = await api(`/chat/api/conversations/${c.id}/delete`, { method: 'POST' });
            const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
            if (success) {
                if (String(currentConvId) === String(c.id)) {
                    currentConvId = null; chatEl.innerHTML = '';
                    try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                    // 删除后显示问候语
                    document.getElementById('greeting')?.remove();
                    loadMessages(); // loadMessages 内部会处理 greeting 显示
                }
                await loadConvs(); // 重新加载列表
                toast('已删除', 'success');
            } else {
                toast(res?.error || '删除失败', 'danger');
            }
            // (Req 5, 9) 改为 remove class
            rowMenu.classList.remove('visible');
        };

        rowMenu.appendChild(rename);
        rowMenu.appendChild(del);
        // rowMenu.style.display = 'none'; // 由 CSS 控制

        if (!document.__convMenuCloserBound__) {
            document.addEventListener('click', (e) => {
                const pops = document.querySelectorAll('.conv-menu-pop');
                pops.forEach(pop => {
                    const parent = pop.parentElement;
                    const btn = parent?.querySelector('.conv-menu');
                    // (Req 5, 9) 改为检查 class 和 remove class
                    if (pop.classList.contains('visible') && !pop.contains(e.target) && e.target !== btn) {
                        pop.classList.remove('visible');
                    }
                });
            });
            document.__convMenuCloserBound__ = true;
        }

        row.appendChild(titleEl);
        row.appendChild(menuBtn);
        row.appendChild(rowMenu);

        // --- (Req 6) 移动端长按支持 ---
        let touchTimer = null;
        row.addEventListener('touchstart', (e) => {
            // 只在移动端（窄屏）且菜单按钮不可见时触发
            if (window.innerWidth > 960 || menuBtn.offsetParent !== null) return;

            touchTimer = setTimeout(async () => {
                touchTimer = null;
                // 确保 e.preventDefault() 只在定时器触发时调用，以允许默认的滚动
                e.preventDefault(); // 阻止后续的 click 和滚动

                // --- (Req 1) 替换 sl-action-sheet ---
                const menuHtml = `
                    <div class="mobile-menu-item" data-action="rename">重命名</div>
                    <div class="mobile-menu-item danger" data-action="delete">删除对话</div>
                `;
                showMobileSheet(menuHtml, '对话选项');

                // 动态绑定点击事件
                const renameBtn = mobileSheetContent.querySelector('[data-action="rename"]');
                const deleteBtn = mobileSheetContent.querySelector('[data-action="delete"]');

                if (renameBtn) {
                    renameBtn.onclick = () => {
                        hideMobileSheet();
                        // 模拟一个事件对象以复用现有逻辑
                        rename.onclick(new Event('click', { bubbles: false }));
                    };
                }
                if (deleteBtn) {
                    deleteBtn.onclick = () => {
                        hideMobileSheet();
                        del.onclick(new Event('click', { bubbles: false }));
                    };
                }
                // --- 结束 (Req 1) 替换 ---

            }, 500); // 500ms 长按
        }, { passive: false }); // 需要 ability to preventDefault

        const clearLongPress = () => {
            if (touchTimer) clearTimeout(touchTimer);
            touchTimer = null;
        };
        row.addEventListener('touchend', clearLongPress);
        row.addEventListener('touchmove', clearLongPress);
        // --- 结束 (Req 6) ---

        convsEl.appendChild(row);
        animateIn(row);
    });
}

async function loadMessages() {
    chatEl.innerHTML = '';
    // (Req 3) 确保问候语被移除
    document.getElementById('greeting')?.remove();

    if (!currentConvId) {
        // 如果没有会话ID，需要重新创建和显示问候语
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
        return;
    }

    const res = await api('/chat/api/messages?conv_id=' + currentConvId);
    const msgs = res?.items || [];

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

    // (Req 3) 更新侧边栏高亮
    document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));

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

    // (Req 3) 更新侧边栏高亮
    document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
    if (currentConvId) {
        const activeRow = Array.from(convsEl.querySelectorAll('.conv')).find(r => r.dataset.id === currentConvId); // 假设 row 有 data-id
        if (activeRow) activeRow.classList.add('active');
    }

    // 无会话则显示问候语
    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = currentConvId ? 'none' : 'block';
    // 有会话则异步加载消息
    if (currentConvId) {
        loadMessages();
    } else {
        // 确保在 /chat 路径时显示问候语
        loadMessages();
    }
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
    // (Req 11) 初始为空，并添加 streaming class
    placeholderContentRef.innerHTML = '';
    placeholderContentRef.classList.add('streaming');

    let acc = '';

    const rerender = (isFinal = false) => {
        // (Req 11) 移除 '▍'
        placeholderContentRef.innerHTML = marked.parse(acc, { breaks: true, gfm: true });
        if (isFinal && window.hljs) {
            // (Req 11) 移除 streaming class
            placeholderContentRef.classList.remove('streaming');
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
        placeholderContentRef.classList.remove('streaming'); // (Req 11) 失败时移除
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
        rerender(true); // (Req 11) 异常时也确保移除光标
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

        // (Req 8) 更新模型按钮外观的辅助函数
        function updateModelButtonLook(modelId, btnElement) {
            const modelConf = MODELS[modelId] || {};
            let iconHtml = `<img src="${modelConf.icon || ''}" style="width:38px;height:38px;border-radius:50%;padding: 3px;">`;

            if (modelId.includes('moonshotai')) {
                btnElement.classList.add('moonshot-dark');
                // Kimi图标在黑色背景上不需要白色padding背景
                iconHtml = `<img src="${modelConf.icon || ''}" style="width:38px;height:38px;border-radius:50%;padding: 0;">`;
            } else {
                btnElement.classList.remove('moonshot-dark');
                // 其他模型图标可能需要白色背景
                iconHtml = `<img src="${modelConf.icon || ''}" style="width:38px;height:38px;border-radius:50%;background-color: white;padding: 3px;">`;
            }
            btnElement.innerHTML = iconHtml;
        }

        // 创建新按钮和弹窗
        const modelBtn = document.createElement('button');
        modelBtn.className = 'btn tonal';
        // (Req 8) 调用辅助函数设置初始外观
        updateModelButtonLook(currentModelId, modelBtn);

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

        const paramSliderHtml = (label, value, max, step) => `
            <div class="param-slider">
                <label><span>${label}</span><input type="number" class="param-input" value="${value}" step="${step}" max="${max}"></label>
                <input type="range" class="param-range" value="${value}" min="0" max="${max}" step="${step}">
            </div>`;

        // (Req 1) 组合移动端模型菜单的 HTML
        const mobileModelMenuHtml = () => `
            <div class="mobile-sheet-group">
                <div class="mobile-sheet-label">模型</div>
                <div class="model-menu mobile">
                    ${Object.entries(MODELS).map(([id, m]) =>
            `<div class="model-item ${id === currentModelId ? 'active' : ''}" data-id="${id}">
                            <img src="${m.icon}"><span>${m.name}</span>
                        </div>`).join('')}
                </div>
            </div>
            <div class="mobile-sheet-group">
                <div class="mobile-sheet-label">Temperature: ${currentTemperature.toFixed(2)}</div>
                ${paramSliderHtml('Temperature', currentTemperature, 2, 0.05)}
            </div>
            <div class="mobile-sheet-group">
                <div class="mobile-sheet-label">Top-P: ${currentTopP.toFixed(2)}</div>
                ${paramSliderHtml('Top-P', currentTopP, 2, 0.05)}
            </div>
        `;

        // 弹窗逻辑
        function createPopover(btn, contentHtml, onOpen, mobileContentHtml = null, mobileLabel = '') {
            const pop = document.createElement('div');
            pop.className = 'toolbar-popover';
            pop.innerHTML = contentHtml;
            document.body.appendChild(pop);

            btn.addEventListener('click', (e) => {
                e.stopPropagation();

                // (Req 1, 7) 替换为自定义移动端底部弹出
                if (window.innerWidth <= 768 && (btn === tempBtn || btn === topPBtn || btn === modelBtn)) {

                    // 统一使用模型按钮的弹窗
                    const fullMobileHtml = mobileModelMenuHtml();
                    showMobileSheet(fullMobileHtml, '模型设置');

                    // --- (Req 1) 动态绑定所有事件 ---

                    // 1. 绑定模型切换
                    mobileSheetContent.querySelectorAll('.model-item').forEach(item => {
                        item.addEventListener('click', () => {
                            currentModelId = item.dataset.id;
                            localStorage.setItem('chat_model', currentModelId);
                            const modelConf = MODELS[currentModelId];
                            currentTemperature = modelConf.temp;
                            currentTopP = modelConf.top_p;

                            updateModelButtonLook(currentModelId, modelBtn);
                            tempBtn.title = `Temperature: ${currentTemperature}`;
                            topPBtn.title = `Top-P: ${currentTopP}`;

                            hideMobileSheet(); // 点击后关闭
                        });
                    });

                    // 2. 绑定 Temp slider
                    const tempSliderBox = mobileSheetContent.querySelector('.param-slider:nth-of-type(1)'); // 第一个 slider
                    if (tempSliderBox) {
                        const labelEl = mobileSheetContent.querySelector('.mobile-sheet-label:nth-of-type(2)'); // 第二个 label
                        setupSlider(tempSliderBox, (val) => {
                            currentTemperature = val;
                            if (labelEl) labelEl.textContent = `Temperature: ${val.toFixed(2)}`;
                        }, tempBtn, 'Temperature');
                    }

                    // 3. 绑定 Top-P slider
                    const topPSliderBox = mobileSheetContent.querySelector('.param-slider:nth-of-type(2)'); // 第二个 slider
                    if (topPSliderBox) {
                        const labelEl = mobileSheetContent.querySelector('.mobile-sheet-label:nth-of-type(3)'); // 第三个 label
                        setupSlider(topPSliderBox, (val) => {
                            currentTopP = val;
                            if (labelEl) labelEl.textContent = `Top-P: ${val.toFixed(2)}`;
                        }, topPBtn, 'Top-P');
                    }

                    return; // 移动端逻辑结束
                }

                // --- 桌面端 popover 逻辑 ---
                const allPops = document.querySelectorAll('.toolbar-popover');
                // (Req 9) 改为检查 class
                const wasOpen = pop.classList.contains('visible');

                // 先隐藏所有弹窗
                allPops.forEach(p => { p.classList.remove('visible'); }); // (Req 9)

                // 如果当前弹窗不是打开状态，则显示它
                if (!wasOpen) {
                    const rect = btn.getBoundingClientRect();
                    // 定位在触发按钮的下方，并对齐右侧
                    pop.style.top = rect.bottom + 8 + 'px';
                    pop.style.left = 'auto';
                    pop.style.right = `${window.innerWidth - rect.right}px`;
                    pop.style.transform = ''; // 确保没有遗留的 transform

                    pop.classList.add('visible'); // (Req 9)
                    if (onOpen) onOpen(pop);
                }
            });
            return pop;
        }

        // (Req 1) 合并桌面端弹窗内容
        const desktopModelMenuHtml = `
            <div class="model-menu">${Object.entries(MODELS).map(([id, m]) =>
            `<div class="model-item ${id === currentModelId ? 'active' : ''}" data-id="${id}">
                    <img src="${m.icon}"><span>${m.name}</span>
                </div>`).join('')}
            </div>
            <div class="popover-divider"></div>
            ${paramSliderHtml('Temperature', currentTemperature, 2, 0.05)}
            <div class="popover-divider"></div>
            ${paramSliderHtml('Top-P', currentTopP, 2, 0.05)}
        `;

        // (Req 1) 移除独立的 Temp/TopP 按钮
        tempBtn.style.display = 'none';
        topPBtn.style.display = 'none';

        // (Req 1) 修改 createPopover 调用
        const modelPop = createPopover(modelBtn, desktopModelMenuHtml, (pop) => {
            // 确保打开时滑块状态同步
            pop.querySelector('.param-slider:nth-of-type(1) .param-input').value = currentTemperature.toFixed(2);
            pop.querySelector('.param-slider:nth-of-type(1) .param-range').value = currentTemperature;
            pop.querySelector('.param-slider:nth-of-type(2) .param-input').value = currentTopP.toFixed(2);
            pop.querySelector('.param-slider:nth-of-type(2) .param-range').value = currentTopP;

            // 更新 active 状态
            pop.querySelectorAll('.model-item').forEach(item => {
                item.classList.toggle('active', item.dataset.id === currentModelId);
            });
        });

        // (Req 1) 绑定桌面端模型切换
        modelPop.querySelectorAll('.model-item').forEach(item => {
            item.addEventListener('click', () => {
                currentModelId = item.dataset.id;
                localStorage.setItem('chat_model', currentModelId);
                const modelConf = MODELS[currentModelId];
                currentTemperature = modelConf.temp;
                currentTopP = modelConf.top_p;

                updateModelButtonLook(currentModelId, modelBtn);
                tempBtn.title = `Temperature: ${currentTemperature}`;
                topPBtn.title = `Top-P: ${currentTopP}`;

                // (Req 1) 更新 active 状态并关闭
                modelPop.querySelectorAll('.model-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                modelPop.classList.remove('visible'); // (Req 9)
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

        // (Req 1) 绑定桌面端 Slider
        setupSlider(modelPop.querySelector('.param-slider:nth-of-type(1)'), (val) => currentTemperature = val, tempBtn, 'Temperature');
        setupSlider(modelPop.querySelector('.param-slider:nth-of-type(2)'), (val) => currentTopP = val, topPBtn, 'Top-P');


        document.addEventListener('click', () => {
            // (Req 9) 改为 remove class
            document.querySelectorAll('.toolbar-popover').forEach(p => p.classList.remove('visible'));
        });

        // (Req 1) 注入新 CSS
        const styles = `
            /* (Req 9) 设置菜单动画 */
            .toolbar-popover { 
                position: fixed; background: var(--panel); border: 1px solid var(--border); 
                border-radius: var(--radius-m); box-shadow: var(--shadow-2); padding: 8px; z-index: 100; 
                visibility: hidden; opacity: 0; transform: scale(0.95) translateY(-10px);
                transform-origin: top right;
                transition: visibility 0s .2s, opacity .2s ease, transform .2s ease;
            }
            .toolbar-popover.visible {
                visibility: visible; opacity: 1; transform: scale(1) translateY(0);
                transition: opacity .2s ease, transform .2s ease;
            }
            .model-menu { display: flex; flex-direction: column; gap: 4px; }
            .model-item { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: var(--radius-s); cursor: pointer; white-space: nowrap; }
            .model-item:hover { background: color-mix(in srgb, var(--panel) 70%, var(--bg)); }
            .model-item.active { 
                background: color-mix(in srgb, var(--accent) 15%, var(--panel));
                color: var(--accent);
                font-weight: 600;
            }
            .model-item img { width: 24px; height: 24px; border-radius: 4px; }
            .param-slider { padding: 8px; display: flex; flex-direction: column; gap: 8px; width: 220px; }
            .param-slider label { display: flex; justify-content: space-between; align-items: center; font-size: 14px; color: var(--muted); }
            .param-input { width: 60px; border: 1px solid var(--border); background: var(--bg); color: var(--text); border-radius: 6px; padding: 4px 6px; font-size: 14px; }
            .param-range { width: 100%; accent-color: var(--accent); }
            .msg .bubble .msg-meta { font-size: 0.8rem; color: var(--muted); margin-top: 8px; }
            
            .popover-divider { height: 1px; background: var(--border); margin: 8px 0; }

            /* --- (Req 1, 4) 自定义移动端弹窗样式 --- */
            .mobile-sheet-overlay {
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,.35);
                opacity: 0;
                visibility: hidden;
                transition: opacity .3s ease, visibility 0s .3s;
                z-index: 100;
            }
            .mobile-sheet-overlay.visible {
                opacity: 1;
                visibility: visible;
                transition: opacity .3s ease;
            }
            .mobile-sheet-panel {
                position: fixed;
                left: 0;
                right: 0;
                bottom: 0;
                background: var(--panel);
                border-top: 1px solid var(--border);
                border-radius: var(--radius-l) var(--radius-l) 0 0;
                box-shadow: var(--shadow-2);
                z-index: 101;
                transform: translateY(100%);
                transition: transform .3s ease;
                max-height: 70vh;
                display: flex;
                flex-direction: column;
            }
            .mobile-sheet-panel.visible {
                transform: translateY(0);
            }
            .mobile-sheet-header {
                font-size: 14px;
                font-weight: 600;
                color: var(--muted);
                padding: 16px 20px 12px;
                border-bottom: 1px solid var(--border);
                text-align: center;
            }
            .mobile-sheet-content {
                overflow-y: auto;
                padding: 8px;
            }
            .mobile-menu-item {
                padding: 14px 20px;
                font-size: 16px;
                cursor: pointer;
                border-radius: var(--radius-s);
            }
            .mobile-menu-item:hover {
                background: color-mix(in srgb, var(--panel) 70%, var(--bg));
            }
            .mobile-menu-item.danger {
                color: var(--sl-color-danger-600);
            }
            .mobile-sheet-group {
                padding: 8px;
                border-bottom: 1px solid var(--border);
            }
            .mobile-sheet-group:last-child {
                border-bottom: none;
            }
            .mobile-sheet-label {
                font-size: 13px;
                font-weight: 600;
                color: var(--muted);
                padding: 8px 8px 4px;
            }
            .model-menu.mobile {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
            }
            .model-menu.mobile .model-item {
                padding: 8px;
                flex-direction: column;
                align-items: flex-start;
                gap: 4px;
            }
            .model-menu.mobile .model-item img { width: 32px; height: 32px; }
            .model-menu.mobile .model-item span { font-size: 14px; }
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
convsEl.addEventListener('click', (e) => {
    // 确保点击的是 .conv 自身或其子元素，但不是菜单按钮
    const convRow = e.target.closest('.conv');
    const menuBtn = e.target.closest('.conv-menu');
    const menuPop = e.target.closest('.conv-menu-pop');

    if (convRow && !menuBtn && !menuPop && window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});