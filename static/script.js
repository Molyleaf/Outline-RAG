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
  alert('已触发全量刷新');
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
  if (res.status === 401) { window.location = '/login'; return null; }
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
  (data || []).forEach(c => {
    const div = document.createElement('div');
    div.className = 'conv' + (c.id === currentConvId ? ' active' : '');
    div.textContent = c.title || ('会话 #' + c.id);
    div.onclick = () => { currentConvId = c.id; loadConvs(); loadMessages(); };
    convsEl.appendChild(div);
  });
}

async function loadMessages() {
  chatEl.innerHTML = '';
  if (!currentConvId) return;
  const msgs = await api('/chat/api/messages?conv_id=' + currentConvId);
  (msgs || []).forEach(m => appendMsg(m.role, m.content));
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
  currentConvId = c.id;
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
    currentConvId = c.id;
    await loadConvs();
  }
  appendMsg('user', text);
  qEl.value = '';

  if (!streamToggle.checked) {
    const res = await api('/chat/api/ask', {method:'POST', body: JSON.stringify({conv_id: currentConvId, query: text, stream: false})});
    appendMsg('assistant', res.answer || '');
    return;
  }

  const placeholder = appendMsg('assistant', '');
  const res = await fetch('/chat/api/ask', {
    method: 'POST',
    body: JSON.stringify({conv_id: currentConvId, query: text, stream: true}),
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
})();
