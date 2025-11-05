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
const MODELS = {
    'deepseek-ai/DeepSeek-V3.2-Exp': { name: 'Deepseek', icon: '/chat/static/img/DeepSeek.svg', temp: 0.7, top_p: 0.7 },
    'moonshotai/Kimi-K2-Instruct-0905': { name: 'Kimi K2', icon: '/chat/static/img/moonshotai_new.png', temp: 0.6, top_p: 0.7 },
    'zai-org/GLM-4.6': { name: 'ChatGLM', icon: '/chat/static/img/thudm.svg', temp: 0.6, top_p: 0.95 },
    'Qwen/Qwen3-Next-80B-A3B-Instruct': { name: 'Qwen3-Next', icon: '/chat/static/img/Tongyi.svg', temp: 0.6, top_p: 0.95 },
    'Qwen/Qwen3-235B-A22B-Thinking-2507': { name: 'Qwen3-Thinking', icon: '/chat/static/img/Tongyi.svg', temp: 0.6, top_p: 0.95 },
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
    // 修复：使用字符串拼接
    el.innerHTML = '<sl-icon name="' + (variant === 'success' ? 'check2-circle' : variant === 'warning' ? 'exclamation-triangle' : variant === 'danger' ? 'x-octagon' : 'info-circle') + '" slot="icon"></sl-icon>' + message;

    // (Req 3) 兼容：若 Shoelace 组件尚未注册，降级为直接打开
    if (typeof el.toast === 'function') {
        // (Req 3) toast() 方法会自动处理附加和移除
        el.toast();
    } else {
        // (Req 3) 降级时才附加到 DOM，并应用定位样式
        el.setAttribute('open', '');
        el.classList.add('toast-fallback'); // 添加一个类以便 CSS 定位

        // [MODIFIED] 修复：内联样式确保在 CSS 加载前 toast 也是 fixed，
        // 防止在 Shoelace 库加载完成前点击时，
        // 元素（作为 'display: block' 或 'inline'）占位并导致滚动条。
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
        // 修复：使用字符串拼接
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
        // 修复：使用字符串拼接
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

/**
 * 辅助函数：将原始文本块作为 fade-in 动画 <span> 附加到容器
 */
function appendFadeInChunk(chunk, container) {
    if (!chunk || !container) return;

    const span = document.createElement('span');
    span.className = 'fade-in-chunk';

    // (Req 1) 修复：不再将 \n 转换 B-R，直接附加文本节点。
    // Markdown 解析器 (parseFn) 会在 finalizeStream 或块分割时处理换行。
    // CSS 中的 white-space: pre-wrap; 会处理显示。
    span.appendChild(document.createTextNode(chunk));

    container.appendChild(span);
    // 始终滚动到底部
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
    // 修复：使用字符串拼接
    return c?.id ? location.origin + '/chat/' + c.id : null;
}