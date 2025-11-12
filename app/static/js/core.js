// app/static/js/core.js
const avatar = document.getElementById('avatar');
const menu = document.getElementById('menu');
const chatEl = document.getElementById('chat');
const convsEl = document.getElementById('convs');
const newConvBtn = document.getElementById('newConv');
const sendBtn = document.getElementById('send');
const qEl = document.getElementById('q');
const refreshAll = document.getElementById('refreshAll');
const fileInput = document.getElementById('fileInput');
const appRoot = document.querySelector('.app');
const hamburger = document.querySelector('.topbar .hamburger');
const sidebarVeil = document.querySelector('.sidebar-veil');
// 计算输入框最大高度（屏幕 20%）
let INPUT_MAX_PX = Math.floor(window.innerHeight * 0.2);
// 主题菜单项（系统/浅色/深色）
const themeRadios = Array.from(document.querySelectorAll('.menu .menu-radio'));

// --- 自定义移动端底部弹窗 ---
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

/** 显示自定义底部弹窗 */
function showMobileSheet(contentHtml, label = '') {
    mobileSheetHeader.textContent = label;
    mobileSheetHeader.style.display = label ? 'block' : 'none';
    mobileSheetContent.innerHTML = contentHtml;
    mobileSheetOverlay.classList.add('visible');
    mobileSheetPanel.classList.add('visible');
}
/** 隐藏自定义底部弹窗 */
function hideMobileSheet() {
    mobileSheetOverlay.classList.remove('visible');
    mobileSheetPanel.classList.remove('visible');
}
// 点击遮罩关闭
mobileSheetOverlay.addEventListener('click', hideMobileSheet);

// --- 模型定义与状态管理 ---
// (新) MODELS 现在从 API 动态加载
let MODELS = {};

// 默认模型为列表第一个，或从 LocalStorage 读取
let currentModelId = localStorage.getItem('chat_model'); // (新) 只读取
// (新) 验证和设置默认值的逻辑移至 app.js/loadUser

let currentTemperature = 0.7; // (新) 临时默认值
let currentTopP = 0.7; // (新) 临时默认值


// 根据模型名称返回头像 URL 的辅助函数 ---
function getAvatarUrlForModel(m) {
    const defaultAvatar = '/chat/static/img/openai.svg';
    if (!m) return defaultAvatar;

    // (新) 尝试从 MODELS 获取配置
    const modelConf = MODELS[m] || {};
    // (新) 优先使用 icon，其次解析 id
    const provider = modelConf.icon ? (m.split('/')[0] || '').toLowerCase() : (m.split('/')[0] || '').toLowerCase();

    if (modelConf.icon) {
        return modelConf.icon;
    }

    // (新) 回退逻辑（如果 icon 字段不存在）
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
    el.innerHTML = '<sl-icon name="' + (variant === 'success' ? 'check2-circle' : variant === 'warning' ? 'exclamation-triangle' : variant === 'danger' ? 'x-octagon' : 'info-circle') + '" slot="icon"></sl-icon>' + message;

    if (typeof el.toast === 'function') {
        el.toast();
    } else {
        el.setAttribute('open', '');
        el.classList.add('toast-fallback');

        el.style.position = 'fixed';
        el.style.top = '24px';
        el.style.right = '24px';
        el.style.zIndex = '200';
        el.style.maxWidth = '400px'; // 额外添加一个最大宽度

        document.body.appendChild(el);
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
        dlg.innerHTML = '<div style="line-height:1.6">' + message + '</div>' +
            '<div slot="footer" style="display:flex;gap:8px;justify-content:flex-end">' +
            '<sl-button class="cancel" variant="neutral">' + cancelText + '</sl-button>' +
            '<sl-button class="ok" variant="primary">' + okText + '</sl-button>' +
            '</div>';
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
        dlg.innerHTML =
            '<sl-input value="' + defaultValue.replace(/"/g, '&quot;') + '" placeholder="' + placeholder.replace(/"/g, '&quot;') + '"></sl-input>' +
            '<div slot="footer" style="display:flex;gap:8px;justify-content:flex-end">' +
            '<sl-button class="cancel" variant="neutral">' + cancelText + '</sl-button>' +
            '<sl-button class="ok" variant="primary">' + okText + '</sl-button>' +
            '</div>';
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

    // 检查 marked.parse (来自 marked.min.js) 或 marked.default.parse (来自 esm 模块的 default export)
    const parse = window.marked.parse || window.marked.default?.parse;

    if (typeof parse !== 'function') {
        const pre = document.createElement('pre');
        pre.textContent = md || '(Markdown 渲染器加载中...)';
        return pre;
    }

    const html = parse(md || '', { breaks: true, gfm: true });
    const wrapper = document.createElement('div');
    wrapper.className = 'md-body';
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

/**
 * 辅助函数：将原始文本块作为 fade-in 动画 <span> 附加到容器
 */
function appendFadeInChunk(chunk, container) {
    if (!chunk || !container) return;

    // (新) Req 2: 简化逻辑，移除 .thinking-content 的特殊处理
    // 始终使用 textNode，让 CSS 'white-space: pre-wrap' 处理换行
    const span = document.createElement('span');
    span.className = 'fade-in-chunk';
    span.appendChild(document.createTextNode(chunk));
    container.appendChild(span);

    // 在增量渲染时，如果 SourcesMap 已经出现，可以尝试对当前容器做一次 citation 处理
    try {
        if (typeof processCitations === 'function') {
            processCitations(container.closest('.bubble-inner') || container);
        }
    } catch (_) {}

    chatEl.scrollTop = chatEl.scrollHeight;
}

// 重命名与删除（确保请求头与响应判定更稳健）
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
    return c?.id ? location.origin + '/chat/' + c.id : null;
}