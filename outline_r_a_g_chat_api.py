import json
from app.rag import answer_query
from app.sync import sync_full_replace, sync_webhook

def handle_index() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Outline RAG Chat</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 0; background: #fafafa; }
    .wrap { max-width: 880px; margin: 0 auto; padding: 20px; }
    .card { background: #fff; border: 1px solid #eee; border-radius: 8px; padding: 16px; margin-top: 20px; }
    textarea { width: 100%; height: 120px; padding: 8px; font-size: 14px; }
    button { padding: 10px 14px; font-size: 14px; }
    .answer { white-space: pre-wrap; margin-top: 10px; }
    .src a { color: #0366d6; text-decoration: none; }
  </style>
</head>
<body>
  <div class="wrap">
    <h2>Outline RAG Chat</h2>
    <div class="card">
      <textarea id="q" placeholder="请输入你的问题..."></textarea>
      <div style="margin-top:10px;">
        <button onclick="ask()">提问</button>
      </div>
      <div id="out" class="answer"></div>
      <div id="src" class="src"></div>
    </div>
  </div>
<script>
async function ask(){
  const q = document.getElementById('q').value.trim();
  if(!q){ return; }
  document.getElementById('out').textContent = '思考中...';
  document.getElementById('src').innerHTML = '';
  const resp = await fetch('./api/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({query:q}) });
  const data = await resp.json();
  document.getElementById('out').textContent = data.answer || '';
  if(data.sources){
    const ul = document.createElement('ul');
    data.sources.forEach(s=>{
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = s.url || '#';
      a.textContent = s.title || s.id;
      a.target = '_blank';
      li.appendChild(a);
      ul.appendChild(li);
    });
    document.getElementById('src').appendChild(ul);
  }
}
</script>
</body>
</html>
"""

def handle_chat_api(body: dict) -> dict:
    q = (body or {}).get("query","").strip()
    if not q:
        return {"answer": "", "sources": [], "error": "empty query"}
    return answer_query(q)

def handle_admin_sync_full() -> dict:
    return sync_full_replace()

def handle_webhook_outline(payload: dict) -> dict:
    return sync_webhook(payload or {})
