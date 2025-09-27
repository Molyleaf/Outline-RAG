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
  const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/(\w[\w-]*)$/);
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

async function loadConvs() {
  const data = await api('/chat/api/conversations');
  convsEl.innerHTML = '';
  const list = data?.items || []; // 保证为数组
  list.forEach(c => {
    const row = document.createElement('div');
    row.className = 'conv' + (String(c.id) === String(currentConvId) ? ' active' : '');
    const titleEl = document.createElement('span');
    titleEl.className = 'conv-title';
    titleEl.textContent = c.title || ('会话 #' + c.id);
    titleEl.onclick = () => {
      // 点击历史会话时，和 ChatGPT 一样跳转到带 GUID 的 URL
      if (c.url) {
        location.href = c.url;
      } else {
        currentConvId = c.id;
        loadConvs();
        loadMessages();
      }
    };

    const menuBtn = document.createElement('button');
    menuBtn.className = 'conv-menu';
    menuBtn.textContent = '⋯';

    const menu = document.createElement('div');
    menu.className = 'conv-menu-pop';
    const rename = document.createElement('div');
    rename.textContent = '重命名';
    const del = document.createElement('div');
    del.textContent = '删除';

    rename.onclick = async (e) => {
      e.stopPropagation();
      const val = prompt('重命名会话', titleEl.textContent);
      if (val == null) { menu.style.display = 'none'; return; }
      const t = val.trim();
      if (!t) { alert('标题不能为空'); return; }
      const res = await api(`/chat/api/conversations/${c.id}`, { method: 'PATCH', body: JSON.stringify({ title: t }) });
      if (res?.ok || res?.status === 'ok') {
        await loadConvs();
      } else {
        alert('重命名失败');
      }
      menu.style.display = 'none';
    };
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm('确定删除该会话？此操作不可恢复。')) { menu.style.display = 'none'; return; }
      const res = await api(`/chat/api/conversations/${c.id}`, { method: 'DELETE' });
      if (res?.ok) {
        if (String(currentConvId) === String(c.id)) { currentConvId = null; chatEl.innerHTML = ''; }
        await loadConvs();
      } else {
        alert('删除失败');
      }
      menu.style.display = 'none';
    };

    menu.appendChild(rename);
    menu.appendChild(del);
    menu.style.display = 'none';

    menuBtn.onclick = (e) => {
      e.stopPropagation();
      menu.style.display = (menu.style.display === 'block') ? 'none' : 'block';
    };
    document.addEventListener('click', (e) => {
      if (!menu.contains(e.target) && e.target !== menuBtn) menu.style.display = 'none';
    });

    row.appendChild(titleEl);
    row.appendChild(menuBtn);
    row.appendChild(menu);
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
  // 统一跳转到包含 GUID 的 URL，避免 400 与状态错乱
  if (c?.url) {
    location.href = c.url;
    return;
  }
  // 兜底：仍旧使用 id
  currentConvId = c?.id;
  await loadConvs();
  await loadMessages();
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
    currentConvId = c?.id;
    await loadConvs();
  }
  appendMsg('user', text);
  qEl.value = '';

  // 流式始终开启：不再依赖隐藏的开关节点
  const placeholder = appendMsg('assistant', '');
  const res = await fetch('/chat/api/ask', {
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
