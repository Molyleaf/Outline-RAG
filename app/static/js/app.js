// app/static/js/app.js

// (新) 用于跟踪正在编辑的消息ID
let currentEditMessageId = null;

async function loadUser() {
    const data = await api('/chat/api/me');
    if (!data || !data.user) {
        // (新) 即使 /api/me 失败，也尝试设置默认模型并初始化UI
        // 这在本地开发或无后端时可能有用
        if (Object.keys(MODELS).length === 0) {
            MODELS = { 'default': { name: 'Default', icon: '', temp: 0.7, top_p: 0.7, beta: false } };
        }
        currentModelId = Object.keys(MODELS)[0];
        if (window.setupTopbarActions) setupTopbarActions();
        return;
    }

    const u = data.user;
    userInfo = u;
    avatar.style.backgroundImage = 'url(\'' + (u.avatar_url || '') + '\')';

    const greetTitle = document.querySelector('#greeting .greet-title');
    if (greetTitle) {
        const name = (u.name || u.username || '').trim();
        greetTitle.textContent = name ? '你好，' + name + '！' : '你好！';
    }

    // --- (新) 动态加载模型 ---
    MODELS = data.models || {};
    const modelIds = Object.keys(MODELS);

    currentModelId = localStorage.getItem('chat_model');

    // 验证存储的模型是否仍在可用列表中
    if (!currentModelId || !MODELS[currentModelId]) {
        currentModelId = modelIds.length > 0 ? modelIds[0] : null;
        if (currentModelId) {
            localStorage.setItem('chat_model', currentModelId);
        } else {
            localStorage.removeItem('chat_model');
        }
    }

    // 设置默认参数
    if (currentModelId && MODELS[currentModelId]) {
        currentTemperature = MODELS[currentModelId].temp;
        currentTopP = MODELS[currentModelId].top_p;
    } else {
        // 如果没有可用模型，设置回退值
        currentTemperature = 0.7;
        currentTopP = 0.7;
    }

    // (新) 确保在模型加载后才初始化顶部栏
    if (window.setupTopbarActions) {
        setupTopbarActions();
    } else {
        console.error("setupTopbarActions not found in main.js");
    }
}

async function loadConvs() {
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
        row.dataset.id = c.id;
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

        rowMenu.appendChild(rename);
        rowMenu.appendChild(del);

        row.addEventListener('click', (e) => {
            if (menuBtn.contains(e.target) || rowMenu.contains(e.target)) return;

            e.preventDefault();
            const href = toSameOriginUrl(c);
            if (!href || href === location.href) return;

            currentConvId = c.id;
            try {
                history.pushState(null, '', href);
            } catch(_) {
                location.href = href;
                return;
            }

            chatEl.innerHTML = '';
            document.getElementById('greeting')?.remove();
            loadMessages();

            document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
            row.classList.add('active');
        });

        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                row.click();
            }
        });

        menuBtn.onclick = (e) => {
            e.stopPropagation();

            const wasOpen = rowMenu.classList.contains('visible');
            const isCustomState = rowMenu.querySelector('.conv-pop-input-group') || rowMenu.querySelector('.conv-pop-confirm-text');

            document.querySelectorAll('.conv-menu-pop.visible').forEach(p => {
                if (p !== rowMenu) {
                    p.classList.remove('visible');
                    const otherRename = p.querySelector('[data-action="rename"]');
                    const otherDel = p.querySelector('[data-action="delete"]');
                    if (otherRename && otherDel) {
                        p.innerHTML = '';
                        p.appendChild(otherRename);
                        p.appendChild(otherDel);
                    }
                }
            });

            rowMenu.innerHTML = '';
            rowMenu.appendChild(rename);
            rowMenu.appendChild(del);

            if (!wasOpen || isCustomState) {
                rowMenu.classList.add('visible');
            } else {
                rowMenu.classList.remove('visible');
            }
        };

        rename.onclick = async (e) => {
            e.stopPropagation();
            const oldTitle = titleEl.textContent;
            rowMenu.innerHTML =
                '<div class="conv-pop-input-group">' +
                '<input type="text" value="' + oldTitle.replace(/"/g, '&quot;') + '">' +
                '<div class="conv-pop-actions">' +
                '<button class="cancel">取消</button>' +
                '<button class="primary ok">确定</button>' +
                '</div>' +
                '</div>';

            const input = rowMenu.querySelector('input');
            input.focus();
            input.select();

            rowMenu.querySelector('.cancel').onclick = (e) => {
                e.stopPropagation();
                rowMenu.classList.remove('visible');
            };

            const handleRename = async () => {
                const val = input.value;
                const t = val.trim();
                if (!t) { toast('标题不能为空', 'warning'); return; }
                if (t === oldTitle) {
                    rowMenu.classList.remove('visible');
                    return;
                }

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
                rowMenu.classList.remove('visible');
            };

            rowMenu.querySelector('.ok').onclick = (e) => { e.stopPropagation(); handleRename(); };
            input.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); handleRename(); } };
        };

        del.onclick = async (e) => {
            e.stopPropagation();

            rowMenu.innerHTML =
                '<div class="conv-pop-confirm-text">确定删除该会话？</div>' +
                '<div class="conv-pop-actions">' +
                '<button class="cancel">取消</button>' +
                '<button class="primary delete">删除</button>' +
                '</div>';

            rowMenu.querySelector('.cancel').onclick = (e) => {
                e.stopPropagation();
                rowMenu.classList.remove('visible');
            };

            rowMenu.querySelector('.delete').onclick = async (e) => {
                e.stopPropagation();

                const res = await api(`/chat/api/conversations/${c.id}/delete`, { method: 'POST' });
                const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
                if (success) {
                    if (String(currentConvId) === String(c.id)) {
                        currentConvId = null; chatEl.innerHTML = '';
                        try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                        document.getElementById('greeting')?.remove();
                        loadMessages();
                    }
                    await loadConvs();
                    toast('已删除', 'success');
                } else {
                    toast(res?.error || '删除失败', 'danger');
                }
                rowMenu.classList.remove('visible');
            };
        };

        rename.dataset.action = 'rename';
        del.dataset.action = 'delete';

        if (!document.__convMenuCloserBound__) {
            document.addEventListener('click', (e) => {
                const pops = document.querySelectorAll('.conv-menu-pop');
                pops.forEach(pop => {
                    const parent = pop.parentElement;
                    const btn = parent?.querySelector('.conv-menu');
                    if (pop.classList.contains('visible') && !pop.contains(e.target) && e.target !== btn) {
                        pop.classList.remove('visible');

                        const renameTpl = pop.querySelector('[data-action="rename"]');
                        const delTpl = pop.querySelector('[data-action="delete"]');
                        if(renameTpl && delTpl) {
                            pop.innerHTML = '';
                            pop.appendChild(renameTpl);
                            pop.appendChild(delTpl);
                        }
                    }
                });
            });
            document.__convMenuCloserBound__ = true;
        }

        row.appendChild(titleEl);
        row.appendChild(menuBtn);
        row.appendChild(rowMenu);

        // --- 移动端长按支持 ---
        let touchTimer = null;
        row.addEventListener('touchstart', (e) => {
            if (window.innerWidth > 960 || menuBtn.offsetParent !== null) return;

            touchTimer = setTimeout(async () => {
                touchTimer = null;
                e.preventDefault();

                const menuHtml =
                    '<div class="mobile-menu-item" data-action="rename">重命名</div>' +
                    '<div class="mobile-menu-item danger" data-action="delete">删除对话</div>';

                showMobileSheet(menuHtml, '对话选项');

                const renameBtn = mobileSheetContent.querySelector('[data-action="rename"]');
                const deleteBtn = mobileSheetContent.querySelector('[data-action="delete"]');

                if (renameBtn) {
                    renameBtn.onclick = () => {
                        hideMobileSheet();
                        (async () => {
                            const val = await promptDialog('重命名会话', titleEl.textContent, { placeholder: '请输入新标题' });
                            if (val == null) return;
                            const t = val.trim();
                            if (!t) { toast('标题不能为空', 'warning'); return; }
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
                        })();
                    };
                }
                if (deleteBtn) {
                    deleteBtn.onclick = () => {
                        hideMobileSheet();
                        (async () => {
                            const ok = await confirmDialog('确定删除该会话？此操作不可恢复。', { okText: '删除', cancelText: '取消' });
                            if (!ok) return;
                            const res = await api(`/chat/api/conversations/${c.id}/delete`, { method: 'POST' });
                            const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
                            if (success) {
                                if (String(currentConvId) === String(c.id)) {
                                    currentConvId = null; chatEl.innerHTML = '';
                                    try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                                    document.getElementById('greeting')?.remove();
                                    loadMessages();
                                }
                                await loadConvs();
                                toast('已删除', 'success');
                            } else {
                                toast(res?.error || '删除失败', 'danger');
                            }
                        })();
                    };
                }

            }, 500);
        }, { passive: false });

        const clearLongPress = () => {
            if (touchTimer) clearTimeout(touchTimer);
            touchTimer = null;
        };
        row.addEventListener('touchend', clearLongPress);
        row.addEventListener('touchmove', clearLongPress);
        // --- 结束 移动端长按支持 ---

        convsEl.appendChild(row);
        animateIn(row);
    });
}

async function loadMessages() {
    chatEl.innerHTML = '';
    document.getElementById('greeting')?.remove();

    if (!currentConvId) {
        let greet = document.getElementById('greeting');
        if (!greet) {
            greet = document.createElement('div');
            greet.id = 'greeting';
            greet.className = 'greeting';
            greet.innerHTML =
                '<div class="greet-title">你好！</div>' +
                '<div class="greet-sub">随时提问，或从以下示例开始</div>' +
                '<div class="greet-suggestions">' +
                '<button class="chip">总结新手教程</button>' +
                '<button class="chip">拉汶帝国完蛋了吗</button>' +
                '<button class="chip">开发组的烂摊子怎么样了</button>' +
                '</div>';
            chatEl.appendChild(greet);
            greet.querySelectorAll('.greet-suggestions .chip').forEach(btn => {
                btn.addEventListener('click', () => {
                    qEl.value = btn.textContent.trim();
                    qEl.focus();
                });
            });
        }
        const greetTitle = greet.querySelector('.greet-title');
        if (greetTitle) {
            const name = (userInfo?.name || userInfo?.username || '').trim();
            greetTitle.textContent = name ? '你好，' + name + '！' : '你好！';
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

    // (新) 存储原始文本和ID
    div.dataset.rawText = text;
    if (metadata.id) {
        div.dataset.messageId = metadata.id;
    }

    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        const avatarUrl = getAvatarUrlForModel(metadata.model);
        avatarEl.style.backgroundImage = 'url(\'' + avatarUrl + '\')';

        if (metadata.model && (metadata.model.includes('moonshotai') || metadata.model.includes('Kimi'))) {
            avatarEl.style.backgroundColor = 'black';
        } else {
            avatarEl.style.backgroundColor = 'white';
        }
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

    // --- (新) 复制和编辑按钮 ---
    const controls = document.createElement('div');
    controls.className = 'msg-controls';

    // 复制按钮 (所有角色)
    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn-icon';
    copyBtn.title = '复制';
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
    copyBtn.onclick = (e) => {
        e.stopPropagation();
        try {
            // 尝试使用现代 API
            navigator.clipboard.writeText(div.dataset.rawText).then(() => {
                toast('已复制', 'success', 1500);
            }, () => {
                // 回退到 execCommand
                throw new Error('Clipboard API failed');
            });
        } catch (err) {
            // execCommand 回退
            const ta = document.createElement('textarea');
            ta.value = div.dataset.rawText;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            document.body.appendChild(ta);
            ta.select();
            try {
                document.execCommand('copy');
                toast('已复制 (回退)', 'success', 1500);
            } catch (copyErr) {
                toast('复制失败', 'danger', 2000);
            }
            document.body.removeChild(ta);
        }
    };
    controls.appendChild(copyBtn);

    // 编辑按钮 (仅限用户)
    if (role === 'user' && metadata.id) {
        const editBtn = document.createElement('button');
        editBtn.className = 'btn-icon';
        editBtn.title = '编辑';
        editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"></path></svg>';
        editBtn.onclick = (e) => {
            e.stopPropagation();
            qEl.value = div.dataset.rawText;
            qEl.focus();
            currentEditMessageId = div.dataset.messageId;
            // (新) 可以在这里添加一个视觉提示，比如输入框边框高亮
            const inputInner = document.querySelector('.input-inner');
            inputInner?.classList.add('editing');
            // 确保文本区域高度自适应
            qEl.dispatchEvent(new Event('input', { bubbles: true }));
        };
        controls.appendChild(editBtn);
    }

    bubble.appendChild(controls);
    // --- 结束 按钮 ---


    if (role === 'assistant' && (metadata.model || metadata.temperature !== undefined)) {
        const metaEl = document.createElement('div');
        metaEl.className = 'msg-meta';
        const modelInfo = MODELS[metadata.model] || {};
        const modelName = modelInfo.name || (metadata.model || 'N/A').split('/')[1];
        const temp = typeof metadata.temperature === 'number' ? metadata.temperature.toFixed(2) : 'N/A';
        const topP = typeof metadata.top_p === 'number' ? metadata.top_p.toFixed(2) : 'N/A';
        const time = metadata.created_at ? new Date(metadata.created_at).toLocaleString() : '';

        let metaText = '模型: ' + modelName + ' · Temp: ' + temp + ' · Top-P: ' + topP;
        if (time) metaText += ' · ' + time;

        metaEl.textContent = metaText;
        bubble.appendChild(metaEl);
    }

    if (role === 'user') {
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

async function sendQuestion() {
    const text = qEl.value.trim();
    if (!text) return;

    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = 'none';

    // (新) 检查是否在编辑
    const messageIdToEdit = currentEditMessageId;
    currentEditMessageId = null; // 重置
    document.querySelector('.input-inner')?.classList.remove('editing'); // 移除高亮

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

    // (新) 如果是编辑，则不追加新消息，而是等待 loadMessages 刷新
    if (!messageIdToEdit) {
        appendMsg('user', text);
    }
    qEl.value = '';

    // --- 启动流式响应 ---

    // (新) 如果是编辑，在发起请求前移除旧消息
    if (messageIdToEdit) {
        let msgNode = document.querySelector(`.msg.user[data-message-id="${messageIdToEdit}"]`);
        if (msgNode) {
            // 移除此消息之后的所有消息
            let nextMsg = msgNode.nextElementSibling;
            while(nextMsg) {
                const toRemove = nextMsg;
                nextMsg = nextMsg.nextElementSibling;
                toRemove.remove();
            }
            // 更新此消息内容
            msgNode.dataset.rawText = text;
            const mdBody = msgNode.querySelector('.md-body');
            if (mdBody) {
                mdBody.innerHTML = ''; // 清空
                mdBody.appendChild(renderMarkdown(text)); // 重新渲染
            }
        }
    }


    const placeholderDiv = appendMsg('assistant', '', {
        model: currentModelId,
        temperature: currentTemperature,
        top_p: currentTopP
    });

    let messageContainer = placeholderDiv.querySelector('.md-body');
    if (!messageContainer) {
        const bubbleInner = placeholderDiv.querySelector('.bubble-inner') || placeholderDiv.querySelector('.bubble') || placeholderDiv;
        const newBody = document.createElement('div');
        newBody.className = 'md-body';
        bubbleInner.appendChild(newBody);
        messageContainer = newBody;
    }
    messageContainer.innerHTML = '';
    messageContainer.classList.add('streaming');

    const loaderEl = document.createElement('div');
    loaderEl.className = 'loading-dots';
    loaderEl.innerHTML = '<span></span><span></span><span></span>';
    messageContainer.appendChild(loaderEl);

    let currentStreamingDiv = document.createElement('div');
    messageContainer.appendChild(currentStreamingDiv);

    let currentStreamingBuffer = '';
    const triggerRegex = /(\n\n+)/;
    const parseFn = window.marked.parse || window.marked.default?.parse;

    let fullRawResponse = ""; // (新) 用于存储完整的原始回复

    const finalizeStream = () => {
        const loader = messageContainer.querySelector('.loading-dots');
        if (loader) loader.remove();

        messageContainer.classList.remove('streaming');
        if (parseFn && currentStreamingBuffer.trim() !== '') {
            try {
                const finalParsedHtml = parseFn(currentStreamingBuffer, { breaks: true, gfm: true });
                currentStreamingDiv.innerHTML = finalParsedHtml;
                if (window.hljs) {
                    currentStreamingDiv.querySelectorAll('pre code').forEach(block => {
                        try { window.hljs.highlightElement(block); } catch(e){}
                    });
                }
            } catch(e) {
                console.error("Final markdown parse error:", e);
                currentStreamingDiv.textContent = currentStreamingBuffer;
            }
        } else if (currentStreamingBuffer.trim() === '') {
            currentStreamingDiv.remove();
        }

        // (新) 流结束后，更新 placeholderDiv 的原始文本，以便复制
        placeholderDiv.dataset.rawText = fullRawResponse;
    };

    // (新) 构建请求体
    const payload = {
        conv_id: currentConvId,
        query: text,
        model: currentModelId,
        temperature: currentTemperature,
        top_p: currentTopP
    };
    if (messageIdToEdit) {
        payload.edit_source_message_id = messageIdToEdit;
    }

    const res = await fetch('/chat/api/ask', {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: {'Content-Type':'application/json'},
        credentials: 'include'
    });

    if (!res.ok) {
        messageContainer.textContent = '请求失败';
        messageContainer.classList.remove('streaming');
        toast('请求失败', 'danger');

        // (新) 如果是编辑失败，刷新消息列表以恢复
        if (messageIdToEdit) {
            await loadMessages();
        }
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let modelDetected = false;
    let streamDone = false;

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
                        streamDone = true;
                        break;
                    }
                    if (data === '[DONE]') {
                        streamDone = true;
                        break;
                    }

                    try {
                        const j = JSON.parse(data);
                        if (!modelDetected && j.model) {
                            const avatarUrl = getAvatarUrlForModel(j.model);
                            const avatarEl = placeholderDiv.querySelector('.avatar');
                            if (avatarEl) {
                                avatarEl.style.backgroundImage = 'url(\'' + avatarUrl + '\')';
                                if (j.model.includes('moonshotai')) {
                                    avatarEl.style.backgroundColor = 'black';
                                } else {
                                    avatarEl.style.backgroundColor = 'white';
                                }
                            }
                            modelDetected = true;
                        }

                        // --- (新) 流式处理核心逻辑 (适配 Thinking) ---
                        const delta = j.choices?.[0]?.delta?.content;
                        const thinking = j.choices?.[0]?.delta?.thinking; // 适配 Thinking
                        const combinedDelta = (delta || '') + (thinking || '');

                        fullRawResponse += combinedDelta; // 累加原始文本

                        // (新) 修复加载动画逻辑
                        const loader = messageContainer.querySelector('.loading-dots');
                        if (loader && combinedDelta.length > 0) {
                            loader.remove();
                        }

                        if (combinedDelta.length > 0) {

                            const lookbehind = currentStreamingBuffer.slice(-5);
                            const testBuffer = lookbehind + combinedDelta;
                            const match = testBuffer.match(triggerRegex);

                            if (match && parseFn) {
                                const triggerStartInDelta = match.index - lookbehind.length;
                                let textBeforeTrigger, triggerAndRest;

                                if (triggerStartInDelta < 0) {
                                    textBeforeTrigger = "";
                                    triggerAndRest = combinedDelta;
                                } else {
                                    textBeforeTrigger = combinedDelta.substring(0, triggerStartInDelta);
                                    triggerAndRest = combinedDelta.substring(triggerStartInDelta);
                                }

                                if (textBeforeTrigger) {
                                    currentStreamingBuffer += textBeforeTrigger;
                                    appendFadeInChunk(textBeforeTrigger, currentStreamingDiv);
                                }

                                if (currentStreamingBuffer.trim() !== '') {
                                    const parsedHtml = parseFn(currentStreamingBuffer, { breaks: true, gfm: true });
                                    currentStreamingDiv.innerHTML = parsedHtml;
                                    if (window.hljs) currentStreamingDiv.querySelectorAll('pre code').forEach(block => {
                                        try { window.hljs.highlightElement(block); } catch(e){}
                                    });
                                } else {
                                    currentStreamingDiv.remove();
                                }

                                currentStreamingDiv = document.createElement('div');
                                messageContainer.appendChild(currentStreamingDiv);

                                currentStreamingBuffer = triggerAndRest;
                                appendFadeInChunk(triggerAndRest, currentStreamingDiv);

                            } else {
                                currentStreamingBuffer += combinedDelta;
                                appendFadeInChunk(combinedDelta, currentStreamingDiv);
                            }
                        }
                        // --- 流式处理核心逻辑结束 ---

                    } catch {}
                }

                if (chunk.includes('data: [DONE]')) {
                    streamDone = true;
                    break;
                }
            }

            if (streamDone) {
                break;
            }

        }

        finalizeStream();

        // (新) 编辑成功后，重新加载消息以获取新 ID
        if (messageIdToEdit) {
            await loadMessages();
        }

    } catch (e) {
        console.error("Stream processing error:", e);
        finalizeStream();
        toast('连接中断', 'warning');
        // (新) 编辑失败，刷新
        if (messageIdToEdit) {
            await loadMessages();
        }
    }
}