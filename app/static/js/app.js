// app/static/js/app.js
async function loadUser() {
    const data = await api('/chat/api/me');
    if (!data || !data.user) return; // (新) 检查 data 和 data.user
    userInfo = data.user;
    MODELS = data.models || {}; // (新) 填充全局 MODELS

    // 主界面右上角仍显示用户头像
    avatar.style.backgroundImage = 'url(\'' + (userInfo.avatar_url || '') + '\')';

    // (新) 验证 currentModelId 并设置默认值
    const availableModelIds = Object.keys(MODELS);
    if (!currentModelId || !MODELS[currentModelId]) {
        currentModelId = availableModelIds[0]; // 使用列表中的第一个作为默认
        if (currentModelId) {
            localStorage.setItem('chat_model', currentModelId);
        }
    }

    // (新) 设置 T 和 P
    if (currentModelId && MODELS[currentModelId]) {
        currentTemperature = MODELS[currentModelId].temp;
        currentTopP = MODELS[currentModelId].top_p;
    } else if (availableModelIds.length > 0) {
        // 如果 currentModelId 仍然无效，但列表不为空
        currentModelId = availableModelIds[0];
        localStorage.setItem('chat_model', currentModelId);
        currentTemperature = MODELS[currentModelId].temp;
        currentTopP = MODELS[currentModelId].top_p;
    } else {
        // (新) 没有可用模型
        console.error("没有可用的模型。");
        currentModelId = null;
    }


    // 仅显示“你好”或“你好，{用户名}！”
    const greetTitle = document.querySelector('#greeting .greet-title');
    if (greetTitle) {
        const name = (userInfo.name || userInfo.username || '').trim();
        greetTitle.textContent = name ? '你好，' + name + '！' : '你好！';
    }
}

async function loadConvs() {
    // 若用户信息未加载，先尝试一次，确保会话接口的鉴权上下文与头像渲染
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
        // 为 pjax popstate 同步高亮添加 data-id
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
            if (!href || href === location.href) return; // 已经是当前会话

            currentConvId = c.id;
            try {
                history.pushState(null, '', href);
            } catch(_) {
                location.href = href; // 回退到跳转
                return;
            }

            chatEl.innerHTML = '';
            document.getElementById('greeting')?.remove();
            loadMessages(); // 手动加载消息

            // 更新侧边栏高亮
            document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
            row.classList.add('active');
        });

        row.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                row.click(); // 触发上面修改过的 click 事件
            }
        });

        menuBtn.onclick = (e) => {
            e.stopPropagation();

            const wasOpen = rowMenu.classList.contains('visible');
            const isCustomState = rowMenu.querySelector('.conv-pop-input-group') || rowMenu.querySelector('.conv-pop-confirm-text');

            // 总是先隐藏所有其他弹窗
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

            // 切换
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
                if (t === oldTitle) { // 标题未变，直接关闭
                    rowMenu.classList.remove('visible');
                    return;
                }

                // API 调用
                const res = await api(`/chat/api/conversations/${c.id}/rename`, {
                    method: 'POST',
                    body: JSON.stringify({ title: t })
                });
                const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
                if (success) {
                    await loadConvs(); // 重新加载列表以更新标题
                    toast('已重命名', 'success');
                } else {
                    toast(res?.error || '重命名失败', 'danger');
                }
                rowMenu.classList.remove('visible'); // 操作后关闭菜单
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
                rowMenu.classList.remove('visible'); // 操作后关闭菜单
            };

            rowMenu.querySelector('.delete').onclick = async (e) => {
                e.stopPropagation();

                // API 调用
                const res = await api(`/chat/api/conversations/${c.id}/delete`, { method: 'POST' });
                const success = (res && (res.ok === true || res.status === 'ok' || res.httpOk === true));
                if (success) {
                    if (String(currentConvId) === String(c.id)) {
                        currentConvId = null; chatEl.innerHTML = '';
                        try { history.replaceState(null, '', '/chat'); } catch(_) { location.href = '/chat'; return; }
                        // 删除后显示问候语
                        document.getElementById('greeting')?.remove();
                        loadMessages(); // loadMessages 内部会处理 greeting 显示
                    }
                    await loadConvs(); // 重新加载列表
                    toast('已删除', 'success');
                } else {
                    toast(res?.error || '删除失败', 'danger');
                }
                rowMenu.classList.remove('visible'); // 操作后关闭菜单
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
                    // 检查 class 并移除
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
            // 只在移动端（窄屏）且菜单按钮不可见时触发
            if (window.innerWidth > 960 || menuBtn.offsetParent !== null) return;

            touchTimer = setTimeout(async () => {
                touchTimer = null;
                // 确保 e.preventDefault() 只在定时器触发时调用，以允许默认的滚动
                e.preventDefault(); // 阻止后续的 click 和滚动

                // --- 使用自定义底部弹窗 ---
                const menuHtml =
                    '<div class="mobile-menu-item" data-action="rename">重命名</div>' +
                    '<div class="mobile-menu-item danger" data-action="delete">删除对话</div>';

                showMobileSheet(menuHtml, '对话选项');

                // 动态绑定点击事件
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
                // --- 结束 移动端菜单 ---

            }, 500); // 500ms 长按
        }, { passive: false }); // 需要 ability to preventDefault

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
    // 确保问候语被移除
    document.getElementById('greeting')?.remove();

    if (!currentConvId) {
        // 如果没有会话ID，需要重新创建和显示问候语
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
            // 绑定示例 chip 点击
            greet.querySelectorAll('.greet-suggestions .chip').forEach(btn => {
                btn.addEventListener('click', () => {
                    qEl.value = btn.textContent.trim();
                    qEl.focus();
                });
            });
        }
        // 若已有 userInfo，立即填充用户名
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

    msgs.forEach(m => appendMsg(m.role, m.content, m, m.id)); // (新) 传入 m.id
    chatEl.scrollTop = chatEl.scrollHeight;
}

// (新) 增加 messageId 参数
function appendMsg(role, text, metadata = {}, messageId = null) {
    const div = document.createElement('div');
    div.className = 'msg ' + role;
    if (messageId) {
        div.dataset.messageId = messageId; // (新) 存储消息 ID
    }

    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        const avatarUrl = getAvatarUrlForModel(metadata.model);
        avatarEl.style.backgroundImage = 'url(\'' + avatarUrl + '\')';

        // Kimi K2 (moonshotai) 使用黑色背景，其他使用白色
        if (metadata.model && metadata.model.includes('moonshotai')) {
            avatarEl.style.backgroundColor = 'black';
        } else {
            // 默认为白色，以确保在暗色模式下也可见 (覆盖CSS)
            avatarEl.style.backgroundColor = 'white';
        }
    } else {
        avatarEl.style.display = 'none';
    }

    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    const bubbleInner = document.createElement('div');
    bubbleInner.className = 'bubble-inner';

    // (新) 提取 Thinking 内容
    let thinkingText = '';
    let contentText = String(text ?? '');
    if (role === 'assistant' && contentText.includes('<!-- THINKING -->')) {
        const match = contentText.match(/<!-- THINKING -->\n([\s\S]*?)\n\n<!-- CONTENT -->\n([\s\S]*)/);
        if (match) {
            thinkingText = match[1];
            contentText = match[2];
        }
    }

    // (新) 如果有 Thinking 内容，则渲染
    if (thinkingText) {
        const thinkingBlock = document.createElement('div');
        thinkingBlock.className = 'thinking-block';
        thinkingBlock.innerHTML =
            '<div class="thinking-header"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><path d="M12 18h.01"/><path d="M12 14a4 4 0 0 0-4-4h0a4 4 0 0 0-4 4v0a4 4 0 0 0 4 4h0a4 4 0 0 0 4-4Z"/></svg><span>Thinking</span></div>' +
            '<div class="thinking-content"></div>';
        thinkingBlock.querySelector('.thinking-content').appendChild(renderMarkdown(thinkingText));
        bubbleInner.appendChild(thinkingBlock);
    }

    const node = renderMarkdown(contentText);
    bubbleInner.appendChild(node);
    bubble.appendChild(bubbleInner);

    // (新) 创建操作按钮容器
    const bubbleActions = document.createElement('div');
    bubbleActions.className = 'bubble-actions';

    // (新) 复制按钮 (Req 5)
    const copyBtn = document.createElement('button');
    copyBtn.className = 'btn-icon copy-btn';
    copyBtn.title = '复制';
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
    copyBtn.onclick = (e) => {
        e.stopPropagation();
        const textToCopy = contentText; // (新) 复制解析后的 content
        const ta = document.createElement('textarea');
        ta.value = textToCopy;
        ta.style.position = 'absolute';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            toast('已复制', 'success', 1500);
        } catch (err) {
            toast('复制失败', 'danger');
        }
        document.body.removeChild(ta);
    };
    bubbleActions.appendChild(copyBtn);

    // (新) 编辑按钮 (Req 4)
    if (role === 'user' && messageId) {
        const editBtn = document.createElement('button');
        editBtn.className = 'btn-icon edit-btn';
        editBtn.title = '编辑';
        editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>';

        editBtn.onclick = (e) => {
            e.stopPropagation();
            qEl.value = contentText; // (新) 复制解析后的 content
            qEl.focus();
            qEl.dataset.editingMessageId = messageId; // 存储 ID

            const inputInner = document.querySelector('.input-inner');
            inputInner.classList.add('is-editing');

            // 添加取消按钮
            let cancelBtn = inputInner.querySelector('.cancel-edit-btn');
            if (!cancelBtn) {
                cancelBtn = document.createElement('button');
                cancelBtn.className = 'btn-icon cancel-edit-btn';
                cancelBtn.title = '取消编辑';
                cancelBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

                cancelBtn.onclick = (ev) => {
                    ev.stopPropagation();
                    delete qEl.dataset.editingMessageId;
                    qEl.value = '';
                    inputInner.classList.remove('is-editing');
                    cancelBtn.remove();
                };
                // 插入到输入框前
                inputInner.prepend(cancelBtn);
            }
        };
        bubbleActions.appendChild(editBtn);
    }

    // (新) 将按钮容器添加到气泡中
    if (role === 'user') {
        bubble.appendChild(bubbleActions);
    } else {
        bubbleInner.appendChild(bubbleActions);
    }


    // --- 新增：显示 AI 回复的元数据 ---
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
        // 放在 bubble-inner 外部，气泡的下方
        bubble.appendChild(metaEl);
    }

    if (role === 'user') {
        // (用户消息不需要占位 div)
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

    // (新) 检查是否处于编辑模式
    const editingId = qEl.dataset.editingMessageId;

    qEl.value = '';
    const ev = new Event('input');
    qEl.dispatchEvent(ev);

    // (新) 如果在编辑，清理 UI
    if (editingId) {
        delete qEl.dataset.editingMessageId;
        const inputInner = document.querySelector('.input-inner');
        inputInner.querySelector('.cancel-edit-btn')?.remove();
        inputInner.classList.remove('is-editing');

        // (新) 编辑模式下，清空该消息之后的所有 DOM 元素
        let msgElement = document.querySelector(`.msg[data-message-id="${editingId}"]`);
        if (msgElement) {
            // 更新该消息的内容
            // (新) 清空旧内容（包括 thinking 和 md-body）
            const bubbleInner = msgElement.querySelector('.bubble-inner');
            if (bubbleInner) {
                bubbleInner.innerHTML = ''; // 完全清空
                bubbleInner.appendChild(renderMarkdown(text)); // 添加新 md-body
                // (新) 重新附加操作按钮
                const bubbleActions = document.createElement('div');
                bubbleActions.className = 'bubble-actions';
                // ... 复制按钮 ...
                const copyBtn = document.createElement('button');
                copyBtn.className = 'btn-icon copy-btn';
                copyBtn.title = '复制';
                copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
                copyBtn.onclick = (e) => {
                    e.stopPropagation();
                    const textToCopy = text; // (新) 复制新文本
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
                // ... 编辑按钮 ...
                const editBtn = document.createElement('button');
                editBtn.className = 'btn-icon edit-btn';
                editBtn.title = '编辑';
                editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4Z"/></svg>';
                editBtn.onclick = (e) => {
                    e.stopPropagation();
                    qEl.value = text;
                    qEl.focus();
                    qEl.dataset.editingMessageId = editingId;
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
                // (新) user 消息的操作按钮在 .bubble 外部
                const bubble = msgElement.querySelector('.bubble');
                if (bubble) bubble.appendChild(bubbleActions);
            }

            // 删除后续所有兄弟节点
            let nextSibling = msgElement.nextElementSibling;
            while (nextSibling) {
                let toRemove = nextSibling;
                nextSibling = nextSibling.nextElementSibling;
                toRemove.remove();
            }
        }
    } else {
        // (新) 非编辑模式才可能创建新会话
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
        // (新) 非编辑模式才追加新用户消息, 并获取 ID
        const newUserMsgDiv = appendMsg('user', text, {}, `temp-id-${Date.now()}`);
        qEl.value = '';

        // (新) 编辑模式下, 我们不知道新消息的 ID，因此无法立即启用编辑
        // (新) 只有在非编辑模式下创建新消息时，我们才会在 loadMessages 之后更新 ID
        // (新) 暂时保持简单：新发送的消息在刷新前无法编辑
    }


    // --- 启动流式响应 ---

    const placeholderDiv = appendMsg('assistant', '', {
        model: currentModelId,
        temperature: currentTemperature,
        top_p: currentTopP
    });

    // 1. 获取 .md-body 作为主容器
    let messageContainer = placeholderDiv.querySelector('.md-body');
    if (!messageContainer) {
        const bubbleInner = placeholderDiv.querySelector('.bubble-inner') || placeholderDiv.querySelector('.bubble') || placeholderDiv;
        const newBody = document.createElement('div');
        newBody.className = 'md-body';
        bubbleInner.appendChild(newBody);
        messageContainer = newBody;
    }
    messageContainer.innerHTML = ''; // 清空（appendMsg 可能会创建带空 <p> 的）
    messageContainer.classList.add('streaming');

    const loaderEl = document.createElement('div');
    loaderEl.className = 'loading-dots';
    loaderEl.innerHTML = '<span></span><span></span><span></span>';
    messageContainer.appendChild(loaderEl);

    // 2. 定义变量
    let currentStreamingDiv = document.createElement('div'); // 第一个用于流式输出的 div
    messageContainer.appendChild(currentStreamingDiv);

    let currentStreamingBuffer = ''; // 用于当前 div 的原始 Markdown 累积
    let currentThinkingBuffer = ''; // (新) 用于 thinking 的累积
    // 仅在 \n\n (一个或多个新行) 处触发渲染
    const triggerRegex = /(\n\n+)/;
    const parseFn = window.marked.parse || window.marked.default?.parse;

    // 3. 定义一个在流结束时（或出错时）调用的最终化函数
    const finalizeStream = () => {
        const loader = messageContainer.querySelector('.loading-dots');
        if (loader) loader.remove();

        messageContainer.classList.remove('streaming');
        // 最终解析*最后*一个流式 div 的内容
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
                currentStreamingDiv.textContent = currentStreamingBuffer; // 回退
            }
        } else if (currentStreamingBuffer.trim() === '') {
            // 如果最后一个缓冲区为空，移除空的 div
            currentStreamingDiv.remove();
        }

        // (新) 最终化后，重新加载消息以获取正确的 ID 并附加按钮
        // (新) 仅在非编辑模式下才自动刷新
        if (!editingId) {
            // (新) 延迟一点点加载，确保数据库已写入
            setTimeout(loadMessages, 100);
        } else {
            // (新) 编辑模式下，手动将 ID 附加到新生成的助手消息上
            // (新) 这太复杂了，暂时也统一使用 loadMessages
            setTimeout(loadMessages, 100);
        }
    };

    // 5. fetch 和 SSE 处理循环
    const res = await fetch('/chat/api/ask', {
        method: 'POST',
        body: JSON.stringify({
            conv_id: currentConvId,
            query: text,
            model: currentModelId,
            temperature: currentTemperature,
            top_p: currentTopP,
            edit_source_message_id: editingId || null // (新) 发送 ID
        }),
        headers: {'Content-Type':'application/json'},
        credentials: 'include'
    });

    if (!res.ok) {
        messageContainer.textContent = '请求失败'; // 替换 (这也会移除加载器)
        messageContainer.classList.remove('streaming');
        toast('请求失败', 'danger');
        return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let modelDetected = false;
    let streamDone = false;
    let firstChunkReceived = false; // (新) Req 1 标志

    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break; // 流自然结束

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

                        // --- 流式处理核心逻辑 ---
                        const delta = j.choices?.[0]?.delta?.content;
                        const thinking = j.choices?.[0]?.delta?.thinking; // (新) Req 2

                        // (新) Req 1: 收到第一个数据块时，移除加载动画
                        const loader = messageContainer.querySelector('.loading-dots');
                        if (!firstChunkReceived && (typeof delta === 'string' && delta.length > 0) || (typeof thinking === 'string' && thinking.length > 0)) {
                            if (loader) loader.remove();
                            firstChunkReceived = true;
                        }

                        // (新) Req 2: 处理 Thinking
                        if (typeof thinking === 'string' && thinking.length > 0) {
                            currentThinkingBuffer = thinking; // (新) Thinking 是状态，直接覆盖
                            let thinkingBlock = messageContainer.querySelector('.thinking-block');
                            if (!thinkingBlock) {
                                thinkingBlock = document.createElement('div');
                                thinkingBlock.className = 'thinking-block';
                                thinkingBlock.innerHTML =
                                    '<div class="thinking-header"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z"/><path d="M12 18h.01"/><path d="M12 14a4 4 0 0 0-4-4h0a4 4 0 0 0-4 4v0a4 4 0 0 0 4 4h0a4 4 0 0 0 4-4Z"/></svg><span>Thinking</span></div>' +
                                    '<div class="thinking-content"></div>';
                                // 插入到 md-body 之前
                                messageContainer.insertBefore(thinkingBlock, currentStreamingDiv);
                            }
                            // Thinking 是状态，覆盖
                            const thinkingContent = thinkingBlock.querySelector('.thinking-content');
                            thinkingContent.innerHTML = ''; // 清空
                            appendFadeInChunk(currentThinkingBuffer, thinkingContent); // 使用 append 支持换行
                        }


                        if (typeof delta === 'string' && delta.length > 0) {

                            // (新) 一旦收到 content，隐藏 thinking
                            let thinkingBlock = messageContainer.querySelector('.thinking-block');
                            if (thinkingBlock && thinkingBlock.style.display !== 'none') {
                                thinkingBlock.style.display = 'none'; // 隐藏
                            }

                            // 使用一个小的回看缓冲区来检查跨 delta 的触发器
                            const lookbehind = currentStreamingBuffer.slice(-5); // 5 字符回看
                            const testBuffer = lookbehind + delta;
                            const match = testBuffer.match(triggerRegex);

                            if (match && parseFn) {
                                // 触发器命中！
                                // 确定触发器在 delta 中的开始位置
                                const triggerStartInDelta = match.index - lookbehind.length;

                                let textBeforeTrigger, triggerAndRest;

                                if (triggerStartInDelta < 0) {
                                    // 触发器在 lookbehind 中开始
                                    // 整个 delta 都属于新块
                                    textBeforeTrigger = "";
                                    triggerAndRest = delta;
                                } else {
                                    // 触发器在 delta 内部开始
                                    // 分割 delta
                                    textBeforeTrigger = delta.substring(0, triggerStartInDelta);
                                    triggerAndRest = delta.substring(triggerStartInDelta);
                                }

                                // A: 处理触发器之前的文本
                                if (textBeforeTrigger) {
                                    currentStreamingBuffer += textBeforeTrigger;
                                    appendFadeInChunk(textBeforeTrigger, currentStreamingDiv);
                                }

                                // B: 解析当前 div 的*完整*缓冲区并替换其内容
                                if (currentStreamingBuffer.trim() !== '') {
                                    const parsedHtml = parseFn(currentStreamingBuffer, { breaks: true, gfm: true });
                                    currentStreamingDiv.innerHTML = parsedHtml;
                                    if (window.hljs) currentStreamingDiv.querySelectorAll('pre code').forEach(block => {
                                        try { window.hljs.highlightElement(block); } catch(e){}
                                    });
                                } else {
                                    currentStreamingDiv.remove(); // 移除空的 div
                                }

                                // C: 创建一个新的 div 用于后续流式传输
                                currentStreamingDiv = document.createElement('div');
                                messageContainer.appendChild(currentStreamingDiv);

                                // D: 使用触发器和剩余文本开始新的缓冲区
                                currentStreamingBuffer = triggerAndRest;
                                appendFadeInChunk(triggerAndRest, currentStreamingDiv);

                            } else {
                                // 没有命中触发器，继续在当前 div 中流式传输
                                currentStreamingBuffer += delta;
                                appendFadeInChunk(delta, currentStreamingDiv);
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

        finalizeStream(); // 处理流在 [DONE] 之前结束的情况
    } catch (e) {
        console.error("Stream processing error:", e);
        finalizeStream(); // 异常时也尝试最终化
        toast('连接中断', 'warning');
    }
}