// app/static/js/app.js

let currentStreamController = null;

function appendFadeInChunk(text, container) {
    if (text) {
        const span = document.createElement('span');
        span.className = 'fade-in-chunk';
        span.textContent = text;
        container.appendChild(span);
        const chatEl = document.querySelector('.chat');
        if (chatEl) {
            chatEl.scrollTop = chatEl.scrollHeight;
        }
    }
}

/**
 * 引用标注处理
 * 将 [来源 x] 文本转换为可点击的链接，并隐藏源数据
 */
function processCitations(element) {
    if (!element) return;

    const scope = element.classList?.contains('bubble-inner') || element.classList?.contains('md-body')
        ? element
        : (element.closest('.bubble-inner') || element);

    let sourcesMap = {};
    const mapWalker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);

    while (mapWalker.nextNode()) {
        const node = mapWalker.currentNode;
        if (node.nodeValue.includes('[SourcesMap]:')) {
            const parent = node.parentElement;
            if (parent) {
                parent.classList.add('source-map-hidden');
                const fullText = parent.textContent;
                const jsonRegex = /\[SourcesMap]:\s*(\{[\s\S]*})/i;
                const match = fullText.match(jsonRegex);
                if (match && match[1]) {
                    try {
                        const parsed = JSON.parse(match[1]);
                        Object.assign(sourcesMap, parsed);
                    } catch (e) {}
                }
            }
        }
    }

    if (Object.keys(sourcesMap).length > 0) {
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
        const nodesToReplace = [];
        const looseCitationRegex = /[\[【(]\s*([^\]】)]*?(?:来源|参考|Source|\d+)[^\]】)]*?)[\]】)]/gi;

        while (walker.nextNode()) {
            const node = walker.currentNode;
            if (node.parentElement && (
                node.parentElement.classList.contains('source-map-hidden') ||
                node.parentElement.closest('.source-map-hidden')
            )) {
                continue;
            }
            if (looseCitationRegex.test(node.nodeValue)) {
                nodesToReplace.push(node);
            }
        }

        nodesToReplace.forEach(node => {
            if (!node.parentElement) return;
            const fragment = document.createDocumentFragment();
            const text = node.nodeValue;

            let lastIndex = 0;
            looseCitationRegex.lastIndex = 0;
            let match;
            while ((match = looseCitationRegex.exec(text)) !== null) {
                fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
                const content = match[1];
                const nums = content.match(/\d+/g);
                let hasValidLink = false;

                if (nums) {
                    const validNums = nums.filter(n => sourcesMap[n]);
                    if (validNums.length > 0) {
                        hasValidLink = true;
                        validNums.forEach(num => {
                            const href = sourcesMap[num];
                            const a = document.createElement('a');
                            a.className = 'citation';
                            a.textContent = `[来源 ${num}]`;
                            a.href = href;
                            a.target = '_blank';
                            a.title = href;
                            fragment.appendChild(a);
                        });
                    }
                }

                if (!hasValidLink) {
                    fragment.appendChild(document.createTextNode(match[0]));
                }
                lastIndex = looseCitationRegex.lastIndex;
            }
            fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
            node.parentElement.replaceChild(fragment, node);
        });
    }
}

async function loadUser() {
    const data = await api('/chat/api/me');
    if (!data || !data.user) return;
    userInfo = data.user;
    MODELS = data.models || {};

    avatar.style.backgroundImage = 'url(\'' + (userInfo.avatar_url || '') + '\')';

    const availableModelIds = Object.keys(MODELS);
    if (!currentModelId || !MODELS[currentModelId]) {
        currentModelId = availableModelIds[0];
        if (currentModelId) {
            localStorage.setItem('chat_model', currentModelId);
        }
    }

    if (currentModelId && MODELS[currentModelId]) {
        currentTemperature = MODELS[currentModelId].temp;
        currentTopP = MODELS[currentModelId].top_p;
    } else if (availableModelIds.length > 0) {
        currentModelId = availableModelIds[0];
        localStorage.setItem('chat_model', currentModelId);
        currentTemperature = MODELS[currentModelId].temp;
        currentTopP = MODELS[currentModelId].top_p;
    } else {
        console.error("没有可用的模型。");
        currentModelId = null;
    }

    const greetTitle = document.querySelector('#greeting .greet-title');
    if (greetTitle) {
        const name = (userInfo.name || userInfo.username || '').trim();
        greetTitle.textContent = name ? '你好，' + name + '！' : '你好！';
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
            try { history.pushState(null, '', href); } catch(_) { location.href = href; return; }
            chatEl.innerHTML = '';
            document.getElementById('greeting')?.remove();
            loadMessages();
            document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
            row.classList.add('active');
        });

        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); row.click(); }
        });

        // 简化的菜单点击逻辑，不再处理行内表单
        menuBtn.onclick = (e) => {
            e.stopPropagation();
            const wasVisible = rowMenu.classList.contains('visible');

            // 关闭所有已打开的菜单
            document.querySelectorAll('.conv-menu-pop.visible').forEach(p => {
                p.classList.remove('visible');
            });

            if (!wasVisible) {
                rowMenu.classList.add('visible');
            }
        };

        // 重命名逻辑：使用全局 Shoelace Dialog
        rename.onclick = async (e) => {
            e.stopPropagation();
            rowMenu.classList.remove('visible'); // 立即关闭小菜单

            const val = await promptDialog('重命名会话', titleEl.textContent, { placeholder: '请输入新标题' });
            if (val === null) return; // 用户取消

            const t = val.trim();
            if (!t) { toast('标题不能为空', 'warning'); return; }
            if (t === titleEl.textContent) return; // 未修改

            const res = await api(`/chat/api/conversations/${c.id}/rename`, {
                method: 'POST',
                body: JSON.stringify({ title: t })
            });
            if (res && (res.ok === true || res.status === 'ok' || res.httpOk === true)) {
                await loadConvs();
                toast('已重命名', 'success');
            } else {
                toast(res?.error || '重命名失败', 'danger');
            }
        };

        // 删除逻辑：使用全局 Shoelace Dialog
        del.onclick = async (e) => {
            e.stopPropagation();
            rowMenu.classList.remove('visible'); // 立即关闭小菜单

            const ok = await confirmDialog('确定删除该会话？此操作不可恢复。', { okText: '删除', cancelText: '取消' });
            if (!ok) return;

            const res = await api(`/chat/api/conversations/${c.id}/delete`, { method: 'POST' });
            if (res && (res.ok === true || res.status === 'ok' || res.httpOk === true)) {
                if (String(currentConvId) === String(c.id)) {
                    currentConvId = null;
                    chatEl.innerHTML = '';
                    try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                    document.getElementById('greeting')?.remove();
                    loadMessages();
                }
                await loadConvs();
                toast('已删除', 'success');
            } else {
                toast(res?.error || '删除失败', 'danger');
            }
        };

        rename.dataset.action = 'rename';
        del.dataset.action = 'delete';

        // 注册全局点击关闭菜单（仅需执行一次）
        if (!document.__convMenuCloserBound__) {
            document.addEventListener('click', (e) => {
                const pops = document.querySelectorAll('.conv-menu-pop');
                pops.forEach(pop => {
                    const parent = pop.parentElement;
                    const btn = parent?.querySelector('.conv-menu');
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
                        // 移动端也复用同样的 logic，promptDialog 已经在 mobile 里使用
                        (async () => {
                            const val = await promptDialog('重命名会话', titleEl.textContent, { placeholder: '请输入新标题' });
                            if (val == null) return;
                            const t = val.trim();
                            if (!t) { toast('标题不能为空', 'warning'); return; }
                            const res = await api(`/chat/api/conversations/${c.id}/rename`, {
                                method: 'POST', body: JSON.stringify({ title: t })
                            });
                            if (res && (res.ok || res.status === 'ok' || res.httpOk)) {
                                await loadConvs(); toast('已重命名', 'success');
                            } else { toast(res?.error || '重命名失败', 'danger'); }
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
                            if (res && (res.ok || res.status === 'ok' || res.httpOk)) {
                                if (String(currentConvId) === String(c.id)) {
                                    currentConvId = null; chatEl.innerHTML = '';
                                    try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                                    document.getElementById('greeting')?.remove(); loadMessages();
                                }
                                await loadConvs(); toast('已删除', 'success');
                            } else { toast(res?.error || '删除失败', 'danger'); }
                        })();
                    };
                }
            }, 500);
        }, { passive: false });

        const clearLongPress = () => { if (touchTimer) clearTimeout(touchTimer); touchTimer = null; };
        row.addEventListener('touchend', clearLongPress);
        row.addEventListener('touchmove', clearLongPress);

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
                '<button class="chip">为拉汶帝国写一段新剧情</button>' +
                '<button class="chip">扮演艾琳与我对话</button>' +
                '</div>';
            chatEl.appendChild(greet);
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
    msgs.forEach(m => appendMsg(m.role, m.content, m, m.id));
    chatEl.scrollTop = chatEl.scrollHeight;
}

function appendMsg(role, text, metadata = {}, messageId = null) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    if (messageId) div.dataset.messageId = messageId;

    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        const avatarUrl = getAvatarUrlForModel(metadata.model);
        avatarEl.style.backgroundImage = 'url(\'' + avatarUrl + '\')';
        if (metadata.model && metadata.model.includes('moonshotai')) {
            avatarEl.style.backgroundColor = 'black';
            avatarEl.style.backgroundSize = 'cover';
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

    let thinkingText = '';
    let contentText = String(text ?? '');
    if (role === 'assistant' && contentText.includes('')) {
        const match = contentText.match(/\n([\s\S]*?)\n\n\n([\s\S]*)/);
        if (match) {
            thinkingText = match[1].trim();
            contentText = match[2].trim();
        }
    }

    if (thinkingText) {
        const thinkingBlock = document.createElement('details');
        thinkingBlock.className = 'thinking-block';
        const summary = document.createElement('summary');
        summary.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><path d="M12 18h.01"/><path d="M12 14a4 4 0 0 0-4-4h0a4 4 0 0 0-4 4v0a4 4 0 0 0 4 4h0a4 4 0 0 0 4-4Z"/></svg><span>显示思考过程</span>';
        const thinkingContent = document.createElement('div');
        thinkingContent.className = 'thinking-content';
        const thinkingInner = document.createElement('div');
        thinkingInner.className = 'md-body';
        thinkingInner.appendChild(renderMarkdown(thinkingText));
        thinkingContent.appendChild(thinkingInner);
        thinkingBlock.appendChild(summary);
        thinkingBlock.appendChild(thinkingContent);
        bubbleInner.appendChild(thinkingBlock);
    }

    const node = renderMarkdown(contentText);
    processCitations(node);
    bubbleInner.appendChild(node);
    bubble.appendChild(bubbleInner);

    const bubbleActions = document.createElement('div');
    bubbleActions.className = 'bubble-actions';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn-icon copy-btn';
    copyBtn.title = '复制';
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
    copyBtn.onclick = (e) => {
        e.stopPropagation();
        const textToCopy = contentText;
        const ta = document.createElement('textarea');
        ta.value = textToCopy;
        ta.style.position = 'absolute';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); toast('已复制', 'success', 1500); } catch (err) { toast('复制失败', 'danger'); }
        document.body.removeChild(ta);
    };
    bubbleActions.appendChild(copyBtn);

    if (role === 'user' && messageId) {
        const editBtn = document.createElement('button');
        editBtn.className = 'btn-icon edit-btn';
        editBtn.title = '编辑';
        editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>';
        editBtn.onclick = (e) => {
            e.stopPropagation();
            qEl.value = contentText;
            qEl.focus();
            qEl.dataset.editingMessageId = messageId;
            const inputInner = document.querySelector('.input-inner');
            inputInner.classList.add('is-editing');
            let cancelBtn = inputInner.querySelector('.cancel-edit-btn');
            if (!cancelBtn) {
                cancelBtn = document.createElement('button');
                cancelBtn.className = 'btn-icon cancel-edit-btn';
                cancelBtn.title = '取消编辑';
                cancelBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
                cancelBtn.onclick = (ev) => { ev.stopPropagation(); delete qEl.dataset.editingMessageId; qEl.value = ''; inputInner.classList.remove('is-editing'); cancelBtn.remove(); };
                inputInner.prepend(cancelBtn);
            }
        };
        bubbleActions.appendChild(editBtn);
    }

    if (role === 'user') bubble.appendChild(bubbleActions);
    else bubbleInner.appendChild(bubbleActions);

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

    if (role === 'user') div.appendChild(bubble);
    else { div.appendChild(avatarEl); div.appendChild(bubble); }

    chatEl.appendChild(div);
    animateIn(div);
    chatEl.scrollTop = chatEl.scrollHeight;
    return div;
}

async function sendQuestion() {
    const text = qEl.value.trim();
    if (!text) return;

    const sendBtn = document.getElementById('send');
    let stopBtn = document.getElementById('stopBtn');
    if (!stopBtn) {
        stopBtn = document.createElement('button');
        stopBtn.id = 'stopBtn';
        if (sendBtn) {
            stopBtn.className = sendBtn.className;
            stopBtn.style.cssText = sendBtn.style.cssText;
        } else {
            stopBtn.className = 'btn';
        }
        stopBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v10H7z"/></svg>';
        stopBtn.style.display = 'none';
        stopBtn.title = '停止';
        sendBtn.parentElement.insertBefore(stopBtn, sendBtn.nextSibling);
        stopBtn.addEventListener('click', () => {
            if (currentStreamController) {
                currentStreamController.abort();
                console.log('Stream aborted by user.');
            }
        });
    }

    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = 'none';

    const editingId = qEl.dataset.editingMessageId;
    qEl.value = '';
    qEl.dispatchEvent(new Event('input'));

    if (editingId) {
        delete qEl.dataset.editingMessageId;
        const inputInner = document.querySelector('.input-inner');
        inputInner.querySelector('.cancel-edit-btn')?.remove();
        inputInner.classList.remove('is-editing');

        let msgElement = document.querySelector(`.msg[data-message-id="${editingId}"]`);
        if (msgElement) {
            const bubbleInner = msgElement.querySelector('.bubble-inner');
            if (bubbleInner) {
                bubbleInner.innerHTML = '';
                const node = renderMarkdown(text);
                processCitations(node);
                bubbleInner.appendChild(node);
                // Re-add actions
                const bubbleActions = document.createElement('div');
                bubbleActions.className = 'bubble-actions';
                const copyBtn = document.createElement('button');
                copyBtn.className = 'btn-icon copy-btn';
                copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    const ta = document.createElement('textarea'); ta.value = text;
                    ta.style.position = 'absolute'; ta.style.left = '-9999px'; document.body.appendChild(ta); ta.select();
                    try { document.execCommand('copy'); toast('已复制', 'success'); } catch(e) { toast('复制失败', 'danger'); }
                    document.body.removeChild(ta);
                };
                bubbleActions.appendChild(copyBtn);
                // Edit button
                const editBtn = document.createElement('button');
                editBtn.className = 'btn-icon edit-btn';
                editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>';
                editBtn.onclick = (e) => {
                    e.stopPropagation();
                    qEl.value = text; qEl.focus(); qEl.dataset.editingMessageId = editingId;
                    const ii = document.querySelector('.input-inner'); ii.classList.add('is-editing');
                    let cb = ii.querySelector('.cancel-edit-btn');
                    if (!cb) {
                        cb = document.createElement('button'); cb.className = 'btn-icon cancel-edit-btn';
                        cb.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
                        cb.onclick = (ev) => { ev.stopPropagation(); delete qEl.dataset.editingMessageId; qEl.value = ''; ii.classList.remove('is-editing'); cb.remove(); };
                        ii.prepend(cb);
                    }
                };
                bubbleActions.appendChild(editBtn);
                msgElement.querySelector('.bubble').appendChild(bubbleActions);
            }
            let nextSibling = msgElement.nextElementSibling;
            while (nextSibling) { let toRemove = nextSibling; nextSibling = nextSibling.nextElementSibling; toRemove.remove(); }
        }
    } else {
        if (!currentConvId) {
            const c = await api('/chat/api/conversations', {method:'POST', body: JSON.stringify({title: text.slice(0,30) || '新会话'})});
            const newId = c?.id;
            const newUrl = (c?.url && c.url.startsWith('/')) ? c.url : (newId ? ('/chat/' + newId) : null);
            if (!newId || !newUrl) { toast('创建会话失败', 'danger'); return; }
            currentConvId = newId;
            try { history.replaceState(null, '', newUrl); } catch(_) { location.href = newUrl; return; }
            try { await loadConvs(); } catch(_) {}
        }
        appendMsg('user', text, {}, `temp-id-${Date.now()}`);
        qEl.value = '';
    }

    if (currentStreamController) currentStreamController.abort();
    currentStreamController = new AbortController();

    if (sendBtn) sendBtn.style.display = 'none';
    if (stopBtn) stopBtn.style.display = 'inline-flex';

    const placeholderDiv = appendMsg('assistant', '', {
        model: currentModelId, temperature: currentTemperature, top_p: currentTopP
    });
    const bubbleInner = placeholderDiv.querySelector('.bubble-inner');
    if (!bubbleInner) return;

    let messageContainer = document.createElement('div');
    messageContainer.className = 'md-body streaming';
    const loaderEl = document.createElement('div');
    loaderEl.className = 'loading-dots';
    loaderEl.innerHTML = '<span></span><span></span><span></span>';
    messageContainer.appendChild(loaderEl);
    bubbleInner.appendChild(messageContainer);

    let currentStreamingDiv = document.createElement('div');
    messageContainer.appendChild(currentStreamingDiv);
    let currentStreamingBuffer = '';

    let currentThinkingStreamingDiv = null;
    let currentThinkingBuffer = '';
    let currentThinkingMdBody = null;
    let thinking_block_created = false;
    let thinking_has_been_collapsed = false;

    const triggerRegex = /(\n\n+)/;
    // 使用 core.js 中定义的 window.parseMarkdownSafe
    // 如果 core.js 未加载完成，则尝试回退到 marked.parse（但不安全）
    const safeParse = window.parseMarkdownSafe || (window.marked ? window.marked.parse : null);

    const finalizeStream = () => {
        const loader = messageContainer.querySelector('.loading-dots');
        if (loader) loader.remove();
        messageContainer.classList.remove('streaming');

        // 结束时必须用 safeParse 解析最终缓冲
        if (safeParse && currentStreamingBuffer.trim() !== '') {
            try {
                const finalParsedHtml = safeParse(currentStreamingBuffer);
                currentStreamingDiv.innerHTML = finalParsedHtml;
                if (window.hljs) currentStreamingDiv.querySelectorAll('pre code').forEach(block => { try{window.hljs.highlightElement(block)}catch(e){} });
            } catch(e) { currentStreamingDiv.textContent = currentStreamingBuffer; }
        } else if (currentStreamingBuffer.trim() === '') {
            currentStreamingDiv.remove();
        }

        // 结束时思考块也必须用 safeParse
        if (safeParse && currentThinkingStreamingDiv && currentThinkingBuffer.trim() !== '') {
            try {
                const finalParsedHtml = safeParse(currentThinkingBuffer);
                currentThinkingStreamingDiv.innerHTML = finalParsedHtml;
                if (window.hljs) currentThinkingStreamingDiv.querySelectorAll('pre code').forEach(block => { try{window.hljs.highlightElement(block)}catch(e){} });
            } catch(e) { currentThinkingStreamingDiv.textContent = currentThinkingBuffer; }
        } else if (currentThinkingStreamingDiv && currentThinkingBuffer.trim() === '') {
            currentThinkingStreamingDiv.remove();
        }

        applyKaTeX(messageContainer);
        if (currentThinkingMdBody) applyKaTeX(currentThinkingMdBody);
        processCitations(messageContainer);
        if (currentThinkingMdBody) processCitations(currentThinkingMdBody);

        if (sendBtn) sendBtn.style.display = 'inline-flex';
        if (stopBtn) stopBtn.style.display = 'none';
        currentStreamController = null;
        setTimeout(loadMessages, 100);
    };

    const res = await fetch('/chat/api/ask', {
        method: 'POST',
        body: JSON.stringify({
            conv_id: currentConvId, query: text, model: currentModelId,
            temperature: currentTemperature, top_p: currentTopP, edit_source_message_id: editingId || null
        }),
        headers: {'Content-Type':'application/json'},
        credentials: 'include',
        signal: currentStreamController.signal
    });

    if (!res.ok) {
        messageContainer.textContent = '请求失败'; messageContainer.classList.remove('streaming');
        toast('请求失败', 'danger'); finalizeStream(); return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let modelDetected = false;
    let streamDone = false;
    let firstChunkReceived = false;

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
                    if (data === '[DONE]') { streamDone = true; break; }
                    try {
                        const j = JSON.parse(data);
                        if (!modelDetected && j.model) {
                            const avatarUrl = getAvatarUrlForModel(j.model);
                            const avatarEl = placeholderDiv.querySelector('.avatar');
                            if (avatarEl) {
                                avatarEl.style.backgroundImage = 'url(\'' + avatarUrl + '\')';
                                if (j.model.includes('moonshotai')) avatarEl.style.backgroundColor = 'black';
                                else avatarEl.style.backgroundColor = 'white';
                            }
                            modelDetected = true;
                        }

                        const delta = j.choices?.[0]?.delta?.content;
                        const thinking = j.choices?.[0]?.delta?.thinking;
                        const loader = messageContainer.querySelector('.loading-dots');
                        if (!firstChunkReceived && ((typeof delta === 'string' && delta.length > 0) || (typeof thinking === 'string' && thinking.length > 0))) {
                            if (loader) loader.remove(); firstChunkReceived = true;
                        }

                        // Thinking handling
                        if (typeof thinking === 'string' && thinking.length > 0) {
                            if (!thinking_block_created) {
                                let thinkingBlock = document.createElement('details');
                                thinkingBlock.className = 'thinking-block';
                                thinkingBlock.setAttribute('open', '');
                                thinkingBlock.innerHTML = '<summary><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><path d="M12 18h.01"/><path d="M12 14a4 4 0 0 0-4-4h0a4 4 0 0 0-4 4v0a4 4 0 0 0 4 4h0a4 4 0 0 0 4-4Z"/></svg><span>思维链</span></summary>';
                                let thinkingContent = document.createElement('div');
                                thinkingContent.className = 'thinking-content';
                                currentThinkingMdBody = document.createElement('div');
                                currentThinkingMdBody.className = 'md-body';
                                thinkingContent.appendChild(currentThinkingMdBody);
                                currentThinkingStreamingDiv = document.createElement('div');
                                currentThinkingMdBody.appendChild(currentThinkingStreamingDiv);
                                thinkingBlock.appendChild(thinkingContent);
                                bubbleInner.insertBefore(thinkingBlock, messageContainer);
                                thinking_block_created = true;
                            }

                            const lookbehind = currentThinkingBuffer.slice(-5);
                            const testBuffer = lookbehind + thinking;
                            const match = testBuffer.match(triggerRegex);

                            if (match && safeParse) {
                                const triggerStartInDelta = match.index - lookbehind.length;
                                let textBeforeTrigger, triggerAndRest;
                                if (triggerStartInDelta < 0) { textBeforeTrigger = ""; triggerAndRest = thinking; }
                                else { textBeforeTrigger = thinking.substring(0, triggerStartInDelta); triggerAndRest = thinking.substring(triggerStartInDelta); }

                                if (textBeforeTrigger) {
                                    currentThinkingBuffer += textBeforeTrigger;
                                    appendFadeInChunk(textBeforeTrigger, currentThinkingStreamingDiv);
                                }
                                if (currentThinkingBuffer.trim() !== '') {
                                    // [修复] 中间态渲染也强制使用 safeParse
                                    const parsedHtml = safeParse(currentThinkingBuffer);
                                    currentThinkingStreamingDiv.innerHTML = parsedHtml;
                                    if (window.hljs) currentThinkingStreamingDiv.querySelectorAll('pre code').forEach(block => { try{window.hljs.highlightElement(block)}catch(e){} });
                                } else { currentThinkingStreamingDiv.remove(); }
                                currentThinkingStreamingDiv = document.createElement('div');
                                currentThinkingMdBody.appendChild(currentThinkingStreamingDiv);
                                currentThinkingBuffer = triggerAndRest;
                                appendFadeInChunk(triggerAndRest, currentThinkingStreamingDiv);
                            } else {
                                currentThinkingBuffer += thinking;
                                appendFadeInChunk(thinking, currentThinkingStreamingDiv);
                            }
                        }

                        // Content handling
                        if (typeof delta === 'string' && delta.length > 0) {
                            if (thinking_block_created && !thinking_has_been_collapsed) {
                                const thinkingBlock = bubbleInner.querySelector('.thinking-block');
                                if (thinkingBlock) {
                                    thinkingBlock.removeAttribute('open');
                                    const summarySpan = thinkingBlock.querySelector('summary span');
                                    if (summarySpan) summarySpan.textContent = '显示思考过程';
                                }
                                thinking_has_been_collapsed = true;
                            }

                            const lookbehind = currentStreamingBuffer.slice(-5);
                            const testBuffer = lookbehind + delta;
                            const match = testBuffer.match(triggerRegex);

                            if (match && safeParse) {
                                const triggerStartInDelta = match.index - lookbehind.length;
                                let textBeforeTrigger, triggerAndRest;
                                if (triggerStartInDelta < 0) { textBeforeTrigger = ""; triggerAndRest = delta; }
                                else { textBeforeTrigger = delta.substring(0, triggerStartInDelta); triggerAndRest = delta.substring(triggerStartInDelta); }

                                if (textBeforeTrigger) {
                                    currentStreamingBuffer += textBeforeTrigger;
                                    appendFadeInChunk(textBeforeTrigger, currentStreamingDiv);
                                }
                                if (currentStreamingBuffer.trim() !== '') {
                                    // [修复] 中间态渲染也强制使用 safeParse
                                    const parsedHtml = safeParse(currentStreamingBuffer);
                                    currentStreamingDiv.innerHTML = parsedHtml;
                                    if (window.hljs) currentStreamingDiv.querySelectorAll('pre code').forEach(block => { try{window.hljs.highlightElement(block)}catch(e){} });
                                } else { currentStreamingDiv.remove(); }
                                currentStreamingDiv = document.createElement('div');
                                messageContainer.appendChild(currentStreamingDiv);
                                currentStreamingBuffer = triggerAndRest;
                                appendFadeInChunk(triggerAndRest, currentStreamingDiv);
                            } else {
                                currentStreamingBuffer += delta;
                                appendFadeInChunk(delta, currentStreamingDiv);
                            }
                        }
                    } catch {}
                }
                if (chunk.includes('data: [DONE]')) { streamDone = true; break; }
            }
            if (streamDone) break;
        }
        finalizeStream();
    } catch (e) {
        if (e.name === 'AbortError') { toast('已停止', 'warning'); }
        else { console.error("Stream processing error:", e); toast('连接中断', 'warning'); }
        finalizeStream();
    }
}

if (chatEl) {
    chatEl.addEventListener('click', (e) => {
        const chip = e.target.closest('.greet-suggestions .chip');
        if (chip) {
            e.preventDefault(); e.stopPropagation();
            if (qEl) {
                qEl.value = chip.textContent.trim();
                qEl.focus();
                qEl.dispatchEvent(new Event('input'));
            }
        }
    });
}