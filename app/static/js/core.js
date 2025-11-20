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

let INPUT_MAX_PX = Math.floor(window.innerHeight * 0.2);
const themeRadios = Array.from(document.querySelectorAll('.menu .menu-radio'));

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

let MODELS = {};
let currentModelId = localStorage.getItem('chat_model');
let currentTemperature = 0.7;
let currentTopP = 0.7;

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

let currentConvId = null;
(function initConvIdFromUrl() {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    if (m) currentConvId = m[1];
})();
let userInfo = null;

function toast(message, variant = 'primary', timeout = 3000) {
    const el = document.createElement('sl-alert');
    el.variant = variant;
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
 * 防止 Markdown 引擎在解析时破坏 LaTeX 公式结构
 */
window.parseMarkdownSafe = function(md) {
    if (!md) return '';

    const mathMap = [];
    // 匹配 LaTeX 公式并替换为占位符
    const protectedMd = md.replace(/(\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$[^$\n]+?(?<!\\)\$)/g, (match) => {
        const key = `___MATH_PLACEHOLDER_${mathMap.length}___`;
        mathMap.push({ key, content: match });
        return key;
    });

    const parse = window.marked.parse || window.marked.default?.parse;
    let html = parse ? parse(protectedMd, { breaks: true, gfm: true }) : protectedMd;

    // 还原公式
    mathMap.forEach(item => {
        html = html.replace(item.key, item.content);
    });

    return html;
};

function renderMarkdown(md) {
    const html = window.parseMarkdownSafe(md || '');
    const wrapper = document.createElement('div');
    wrapper.className = 'md-body';
    wrapper.removeAttribute('style');
    wrapper.innerHTML = html;

    applyKaTeX(wrapper);

    if (window.hljs) {
        wrapper.querySelectorAll('pre code').forEach(block => window.hljs.highlightElement(block));
    }
    return wrapper;
}

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