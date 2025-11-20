// app/static/js/core.js

// --- 全局 DOM 元素引用 ---
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
const themeRadios = Array.from(document.querySelectorAll('.menu .menu-radio'));

// --- 自定义移动端底部动作面板 (Action Sheet) ---
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

/**
 * 预加载 Shoelace 组件，防止网络延迟导致 UI 闪烁
 */
function preloadShoelaceComponents() {
    const components = ['sl-alert', 'sl-dialog', 'sl-input', 'sl-button', 'sl-icon'];
    const preloadContainer = document.createElement('div');
    preloadContainer.style.display = 'none';
    preloadContainer.id = 'shoelace-preloader';

    components.forEach(tag => {
        try {
            if (!customElements.get(tag)) {
                const el = document.createElement(tag);
                preloadContainer.appendChild(el);
            }
        } catch (e) {}
    });

    if (preloadContainer.children.length > 0) {
        document.body.appendChild(preloadContainer);
        setTimeout(() => { preloadContainer.remove(); }, 1000);
    }
}

// --- 移动端面板控制函数 ---
function showMobileSheet(contentHtml, label = '') {
    mobileSheetHeader.textContent = label;
    mobileSheetHeader.style.display = label ? 'block' : 'none';
    mobileSheetContent.innerHTML = contentHtml;
    mobileSheetOverlay.classList.add('visible');
    mobileSheetPanel.classList.add('visible');
}

function hideMobileSheet() {
    mobileSheetOverlay.classList.remove('visible');
    mobileSheetPanel.classList.remove('visible');
}
mobileSheetOverlay.addEventListener('click', hideMobileSheet);

// --- 全局状态变量 ---
let MODELS = {};
let currentModelId = localStorage.getItem('chat_model');
let currentTemperature = 0.7;
let currentTopP = 0.7;

// 获取模型头像
function getAvatarUrlForModel(m) {
    const defaultAvatar = '/chat/static/img/openai.svg';
    if (!m) return defaultAvatar;

    const modelConf = MODELS[m] || {};
    const provider = modelConf.icon ? (m.split('/')[0] || '').toLowerCase() : (m.split('/')[0] || '').toLowerCase();

    if (modelConf.icon) return modelConf.icon;

    if (provider === 'deepseek-ai') return '/chat/static/img/DeepSeek.svg';
    else if (provider === 'qwen') return '/chat/static/img/Tongyi.svg';
    else if (provider === 'moonshotai') return '/chat/static/img/moonshotai_new.png';
    else if (provider === 'zai-org' || provider === 'thudm') return '/chat/static/img/thudm.svg';
    else if (provider === 'inclusionai') return '/chat/static/img/ling.png';
    else return defaultAvatar;
}

// 从 URL 初始化当前会话 ID
let currentConvId = null;
(function initConvIdFromUrl() {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    if (m) currentConvId = m[1];
})();
let userInfo = null;

// --- UI 工具函数 (Toast, Dialog) ---

function toast(message, variant = 'primary', timeout = 3000) {
    const el = document.createElement('sl-alert');
    el.variant = variant;
    el.closable = true;
    el.innerHTML = '<sl-icon name="' + (variant === 'success' ? 'check2-circle' : variant === 'warning' ? 'exclamation-triangle' : variant === 'danger' ? 'x-octagon' : 'info-circle') + '" slot="icon"></sl-icon>' + message;

    if (typeof el.toast === 'function') {
        el.toast();
    } else {
        // 降级处理
        el.setAttribute('open', '');
        el.classList.add('toast-fallback');
        el.style.position = 'fixed';
        el.style.top = '24px';
        el.style.right = '24px';
        el.style.zIndex = '200';
        el.style.maxWidth = '400px';
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

        const hideDialog = () => {
            if (typeof dlg.hide === 'function') dlg.hide(); else dlg.removeAttribute('open');
        };

        dlg.addEventListener('sl-after-hide', () => dlg.remove());
        dlg.querySelector('.cancel').addEventListener('click', () => { hideDialog(); resolve(false); });
        dlg.querySelector('.ok').addEventListener('click', () => { hideDialog(); resolve(true); });

        if (typeof dlg.show === 'function') dlg.show(); else dlg.setAttribute('open', '');
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

        const hideDialog = () => {
            if (typeof dlg.hide === 'function') dlg.hide(); else dlg.removeAttribute('open');
        };

        function done(val) { hideDialog(); resolve(val); }
        dlg.addEventListener('sl-after-hide', () => dlg.remove());
        dlg.querySelector('.cancel').addEventListener('click', () => done(null));
        dlg.querySelector('.ok').addEventListener('click', () => done(input.value.trim()));
        dlg.addEventListener('sl-initial-focus', () => input.focus());

        if (typeof dlg.show === 'function') dlg.show(); else dlg.setAttribute('open', '');
    });
}

/**
 * 安全的 Markdown 解析函数
 * 作用：在调用 marked.parse 之前，先将 LaTeX 公式提取出来替换为纯字母占位符。
 * 防止 Markdown 引擎破坏公式结构（例如将 _ 解析为斜体，或将 \\ 解析为转义符）。
 * 解析完成后，再将占位符还原为原始 LaTeX 公式。
 */
window.parseMarkdownSafe = function(md) {
    if (!md) return '';

    const mathMap = [];

    // 正则匹配 LaTeX：
    // 1. $$...$$ (块级)
    // 2. \[...\] (块级)
    // 3. \(...\) (行内)
    // 4. $...$ (行内，排除转义的 \$)
    // 关键：占位符 MATHMASK...ENDMASK 不包含下划线等特殊符号，Markdown 引擎会将其视为普通单词处理。
    const protectedMd = md.replace(/(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$[^$\n]+?(?<!\\)\$)/g, (match) => {
        const key = `MATHMASK${mathMap.length}ENDMASK`;
        mathMap.push({ key, content: match });
        return key;
    });

    // 调用 Marked.js 进行解析
    const parse = window.marked.parse || window.marked.default?.parse;
    // 如果 marked 未加载，则直接返回原文（避免报错）
    let html = parse ? parse(protectedMd, { breaks: true, gfm: true }) : protectedMd;

    // 还原 LaTeX 公式
    mathMap.forEach(item => {
        // 使用 split/join 进行全局替换，比 replaceAll 兼容性更好，且不会解析 content 中的特殊字符
        html = html.split(item.key).join(item.content);
    });

    return html;
};

/**
 * 渲染 Markdown 的入口函数
 * 1. 安全解析 Markdown -> HTML
 * 2. 渲染 LaTeX (KaTeX)
 * 3. 代码高亮 (Highlight.js)
 */
function renderMarkdown(md) {
    // 使用自定义的安全解析器
    const html = window.parseMarkdownSafe(md || '');

    const wrapper = document.createElement('div');
    wrapper.className = 'md-body';
    wrapper.removeAttribute('style');
    wrapper.innerHTML = html;

    // 渲染数学公式
    applyKaTeX(wrapper);

    // 渲染代码高亮
    if (window.hljs) {
        wrapper.querySelectorAll('pre code').forEach(block => window.hljs.highlightElement(block));
    }
    return wrapper;
}

// 简单的淡入动画
function animateIn(el) {
    el.animate([{ transform: 'translateY(6px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }], {
        duration: 160,
        easing: 'cubic-bezier(.2,.8,.2,1)'
    });
}

function appendFadeInChunk(chunk, container) {
    if (!chunk || !container) return;
    const span = document.createElement('span');
    span.className = 'fade-in-chunk';
    span.appendChild(document.createTextNode(chunk));
    container.appendChild(span);
    chatEl.scrollTop = chatEl.scrollHeight;
}

// 通用 API 请求封装
async function api(path, opts) {
    const init = { credentials: 'include', ...(opts || {}) };
    init.headers = { 'Content-Type': 'application/json', ...(opts && opts.headers || {}) };
    const res = await fetch(path, init);
    if (res.status === 401) { window.location = '/chat/login'; return null; }
    if ((opts && opts.stream) || res.headers.get('content-type')?.includes('text/event-stream')) {
        return res;
    }
    try { return await res.json(); } catch { return { httpOk: res.ok }; }
}

function toSameOriginUrl(c) {
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

/**
 * KaTeX 渲染函数
 * 配置了常见的 LaTeX 分隔符
 */
function applyKaTeX(element) {
    if (window.renderMathInElement) {
        window.renderMathInElement(element, {
            delimiters: [
                {left: '$$', right: '$$', display: true},
                {left: '$', right: '$', display: false},
                {left: '\\(', right: '\\)', display: false},
                {left: '\\[', right: '\\]', display: true}
            ],
            throwOnError: false
        });
    }
}