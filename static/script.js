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

let currentConvId = null;
// 尝试从 URL /chat/<guid> 解析当前会话（与后端返回的 url 对齐）
(function initConvIdFromUrl(){
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    if (m) currentConvId = m[1];
})();
let userInfo = null;

avatar.addEventListener('click', () => {
    menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
});
document.addEventListener('click', (e) => {
    if (!avatar.contains(e.target) && !menu.contains(e.target)) menu.style.display = 'none';
});
refreshAll.addEventListener('click', async (e) => {
    e.preventDefault();
    await fetch('/chat/update/all', {method: 'POST', credentials: 'include'});
    alert('已完成全量刷新');
});
fileInput.addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const form = new FormData();
    form.append('file', f);
    const res = await fetch('/chat/api/upload', { method: 'POST', body: form, credentials: 'include' });
    if (res.ok) alert('上传成功，已加入索引'); else alert('上传失败');
    e.target.value = '';
});

async function api(path, opts) {
    const res = await fetch(path, {credentials: 'include', headers: {'Content-Type':'application/json', ...(opts && opts.headers || {})}, ...opts});
    if (res.status === 401) { window.location = '/chat/login'; return null; }
    if ((opts && opts.stream) || res.headers.get('content-type')?.includes('text/event-stream')) {
        return res; // 流式
    }
    return res.json();
}

async function loadUser() {
    const u = await api('/chat/api/me');
    if (!u) return;
    userInfo = u;
    avatar.style.backgroundImage = `url('${u.avatar_url || ''}')`;
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
    const list = data?.items || []; // 保证为数组
    list.forEach(c => {
        const row = document.createElement('div');
        row.className = 'conv' + (String(c.id) === String(currentConvId) ? ' active' : '');
        row.tabIndex = 0; // 可键盘聚焦
        const titleEl = document.createElement('span');
        titleEl.className = 'conv-title';
        titleEl.textContent = c.title || ('会话 ' + (c.id || '').slice(0,8));

        const menuBtn = document.createElement('button');
        menuBtn.className = 'conv-menu';
        menuBtn.textContent = '⋯';

        // 避免与顶部 menu 变量名冲突
        const rowMenu = document.createElement('div');
        rowMenu.className = 'conv-menu-pop';
        const rename = document.createElement('div');
        rename.textContent = '重命名';
        const del = document.createElement('div');
        del.textContent = '删除';

        // 行点击：任何非菜单区域点击都跳转
        function go() {
            const href = toSameOriginUrl(c);
            if (href) location.href = href;
        }
        row.addEventListener('click', (e) => {
            // 点击菜单按钮或弹层时不跳转
            if (menuBtn.contains(e.target) || rowMenu.contains(e.target)) return;
            go();
        });
        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                go();
            }
        });

        // 标题点击也可跳转（与行点击一致）
        titleEl.onclick = (e) => {
            e.stopPropagation();
            go();
        };

        menuBtn.onclick = (e) => {
            e.stopPropagation();
            rowMenu.style.display = (rowMenu.style.display === 'block') ? 'none' : 'block';
        };

        rename.onclick = async (e) => {
            e.stopPropagation();
            const val = prompt('重命名会话', titleEl.textContent);
            if (val == null) { rowMenu.style.display = 'none'; return; }
            const t = val.trim();
            if (!t) { alert('标题不能为空'); return; }
            const res = await api(`/chat/api/conversations/${c.id}`, { method: 'PATCH', body: JSON.stringify({ title: t }) });
            if (res?.ok || res?.status === 'ok') {
                await loadConvs();
            } else {
                alert('重命名失败');
            }
            rowMenu.style.display = 'none';
        };
        del.onclick = async (e) => {
            e.stopPropagation();
            if (!confirm('确定删除该会话？此操作不可恢复。')) { rowMenu.style.display = 'none'; return; }
            const res = await api(`/chat/api/conversations/${c.id}`, { method: 'DELETE' });
            if (res?.ok) {
                if (String(currentConvId) === String(c.id)) { currentConvId = null; chatEl.innerHTML = ''; }
                await loadConvs();
            } else {
                alert('删除失败');
            }
            rowMenu.style.display = 'none';
        };

        rowMenu.appendChild(rename);
        rowMenu.appendChild(del);
        rowMenu.style.display = 'none';

        // 单一的全局委托，避免为每个行重复绑定
        // 注：此监听只注册一次
        if (!document.__convMenuCloserBound__) {
            document.addEventListener('click', (e) => {
                // 点击任意非菜单、非按钮区域时收起所有行内菜单
                document.querySelectorAll('.conv-menu-pop').forEach(pop => {
                    const btn = pop.previousSibling; // 我们的结构：titleEl, menuBtn, rowMenu => previousSibling 不是按钮，改为更稳妥查找
                });
                // 更稳妥：逐个判断
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
    });
}

async function loadMessages() {
    chatEl.innerHTML = '';
    if (!currentConvId) return;
    const res = await api('/chat/api/messages?conv_id=' + currentConvId);
    const msgs = res?.items || []; // 服务端返回对象，取 items
    msgs.forEach(m => appendMsg(m.role, m.content));
    chatEl.scrollTop = chatEl.scrollHeight;
}

function appendMsg(role, text) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    div.textContent = text;
    chatEl.appendChild(div);
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
    const placeholder = appendMsg('assistant', '');
    const res = await fetch('/chat/api/ask', { // 始终开启 SSE
        method: 'POST',
        body: JSON.stringify({conv_id: currentConvId, query: text}),
        headers: {'Content-Type':'application/json'},
        credentials: 'include'
    });

    if (!res.ok) {
        placeholder.textContent = '请求失败';
        return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
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
                    return;
                }
                try {
                    const j = JSON.parse(data);
                    if (j.delta) placeholder.textContent += j.delta;
                } catch {}
            }
        }
    }
}

(async function init(){
    await loadUser();
    await loadConvs();
    // 初次进入带 GUID 的地址时加载消息
    if (currentConvId) {
        await loadMessages();
    }
})();