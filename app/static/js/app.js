async function loadUser() {
    const u = await api('/chat/api/me');
    if (!u) return;
    userInfo = u;
    // 主界面右上角仍显示用户头像
    avatar.style.backgroundImage = `url('${u.avatar_url || ''}')`;

    // 仅显示“你好”或“你好，{用户名}！”
    const greetTitle = document.querySelector('#greeting .greet-title');
    if (greetTitle) {
        const name = (u.name || u.username || '').trim();
        greetTitle.textContent = name ? `你好，${name}！` : '你好！';
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

        // (Req 4) 将标准菜单项附加到 rowMenu，以便后续重置
        rowMenu.appendChild(rename);
        rowMenu.appendChild(del);

        // 修改点击逻辑为 PJAX (History API)
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
            document.getElementById('greeting')?.remove(); // 移除问候语
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

        // titleEl.onclick = (e) => { e.stopPropagation(); go(); }; // 已被 row click 替代

        // (Req 4) 重构菜单点击逻辑
        menuBtn.onclick = (e) => {
            e.stopPropagation();

            const wasOpen = rowMenu.classList.contains('visible');
            const isCustomState = rowMenu.querySelector('.conv-pop-input-group') || rowMenu.querySelector('.conv-pop-confirm-text');

            // 总是先隐藏所有其他弹窗
            document.querySelectorAll('.conv-menu-pop.visible').forEach(p => {
                if (p !== rowMenu) {
                    p.classList.remove('visible');
                    // (Req 4) 重置其他已打开的弹窗
                    const otherRename = p.querySelector('[data-action="rename"]');
                    const otherDel = p.querySelector('[data-action="delete"]');
                    if (otherRename && otherDel) {
                        p.innerHTML = '';
                        p.appendChild(otherRename);
                        p.appendChild(otherDel);
                    }
                }
            });

            // (Req 4) 总是重置当前菜单内容
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

        // (Req 4) 重构重命名逻辑，使用内联表单
        rename.onclick = async (e) => {
            e.stopPropagation();
            const oldTitle = titleEl.textContent;
            rowMenu.innerHTML = `
                <div class="conv-pop-input-group">
                    <input type="text" value="${oldTitle.replace(/"/g, '&quot;')}">
                    <div class="conv-pop-actions">
                        <button class="cancel">取消</button>
                        <button class="primary ok">确定</button>
                    </div>
                </div>`;

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

        // (Req 4) 重构删除逻辑，使用内联确认
        del.onclick = async (e) => {
            e.stopPropagation();

            rowMenu.innerHTML = `
                <div class="conv-pop-confirm-text">确定删除该会话？</div>
                <div class="conv-pop-actions">
                    <button class="cancel">取消</button>
                    <button class="primary delete">删除</button>
                </div>`;

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

        // (Req 4) 原始的 rename 和 del div 现在作为模板，保存其引用
        rename.dataset.action = 'rename';
        del.dataset.action = 'delete';

        // rowMenu.appendChild(rename); // 已在顶部添加
        // rowMenu.appendChild(del); // 已在顶部添加
        // rowMenu.style.display = 'none'; // 由 CSS 控制

        if (!document.__convMenuCloserBound__) {
            document.addEventListener('click', (e) => {
                const pops = document.querySelectorAll('.conv-menu-pop');
                pops.forEach(pop => {
                    const parent = pop.parentElement;
                    const btn = parent?.querySelector('.conv-menu');
                    // 检查 class 并移除
                    if (pop.classList.contains('visible') && !pop.contains(e.target) && e.target !== btn) {
                        pop.classList.remove('visible');

                        // (Req 4) 点击外部时重置菜单内容
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
                const menuHtml = `
                    <div class="mobile-menu-item" data-action="rename">重命名</div>
                    <div class="mobile-menu-item danger" data-action="delete">删除对话</div>
                `;
                showMobileSheet(menuHtml, '对话选项');

                // 动态绑定点击事件
                const renameBtn = mobileSheetContent.querySelector('[data-action="rename"]');
                const deleteBtn = mobileSheetContent.querySelector('[data-action="delete"]');

                if (renameBtn) {
                    renameBtn.onclick = () => {
                        hideMobileSheet();
                        // (Req 4) 移动端触发 Shoelace promptDialog
                        // (注意：移动端弹窗未要求修改，保持原 Shoelace 逻辑)
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
                        // (Req 4) 移动端触发 Shoelace confirmDialog
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
            greet.innerHTML = `
                 <div class="greet-title">你好！</div>
                 <div class="greet-sub">随时提问，或从以下示例开始</div>
                 <div class="greet-suggestions">
                     <button class="chip">总结新手教程</button>
                     <button class="chip">拉汶帝国完蛋了吗</button>
                     <button class="chip">开发组的烂摊子怎么样了</button>
                 </div>
             `;
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
            greetTitle.textContent = name ? `你好，${name}！` : '你好！';
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

    const avatarEl = document.createElement('div');
    avatarEl.className = 'avatar';
    if (role === 'assistant') {
        const avatarUrl = getAvatarUrlForModel(metadata.model);
        avatarEl.style.backgroundImage = `url('${avatarUrl}')`;

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

    const node = renderMarkdown(String(text ?? ''));
    bubbleInner.appendChild(node);
    bubble.appendChild(bubbleInner);

    // --- 新增：显示 AI 回复的元数据 ---
    if (role === 'assistant' && (metadata.model || metadata.temperature !== undefined)) {
        const metaEl = document.createElement('div');
        metaEl.className = 'msg-meta';
        const modelInfo = MODELS[metadata.model] || {};
        const modelName = modelInfo.name || (metadata.model || 'N/A').split('/')[1];
        const temp = typeof metadata.temperature === 'number' ? metadata.temperature.toFixed(2) : 'N/A';
        const topP = typeof metadata.top_p === 'number' ? metadata.top_p.toFixed(2) : 'N/A';
        const time = metadata.created_at ? new Date(metadata.created_at).toLocaleString() : '';

        let metaText = `模型: ${modelName} · Temp: ${temp} · Top-P: ${topP}`;
        if (time) metaText += ` · ${time}`;

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

    appendMsg('user', text);
    qEl.value = '';

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

    // (Req 1) 添加加载动画
    const loaderEl = document.createElement('div');
    loaderEl.className = 'loading-dots';
    loaderEl.innerHTML = '<span></span><span></span><span></span>';
    messageContainer.appendChild(loaderEl);

    // 2. 定义变量
    let currentStreamingDiv = document.createElement('div'); // 第一个用于流式输出的 div
    messageContainer.appendChild(currentStreamingDiv);

    let currentStreamingBuffer = ''; // 用于当前 div 的原始 Markdown 累积
    // 仅在 \n\n (一个或多个新行) 处触发渲染
    const triggerRegex = /(\n\n+)/;
    const parseFn = window.marked.parse || window.marked.default?.parse;

    // 3. 定义一个在流结束时（或出错时）调用的最终化函数
    const finalizeStream = () => {
        // (Req 1) 确保加载器在最终化时被移除
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
    };

    // 4. (rerender 函数已被移除)

    // 5. fetch 和 SSE 处理循环
    const res = await fetch('/chat/api/ask', {
        method: 'POST',
        body: JSON.stringify({
            conv_id: currentConvId,
            query: text,
            model: currentModelId,
            temperature: currentTemperature,
            top_p: currentTopP
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
                        // finalizeStream(); // 将在循环外调用
                        // return; // 不要在这里 return，让循环自然结束
                        break; // 跳出 while (idx) 循环
                    }
                    if (data === '[DONE]') break; // (修正) 应该跳出外层 while (true) 循环，但 finalizeStream 在外部处理

                    try {
                        const j = JSON.parse(data);
                        if (!modelDetected && j.model) {
                            const avatarUrl = getAvatarUrlForModel(j.model);
                            const avatarEl = placeholderDiv.querySelector('.avatar');
                            if (avatarEl) {
                                avatarEl.style.backgroundImage = `url('${avatarUrl}')`;

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

                        // (Req 1) 收到第一个数据块时，移除加载动画
                        const loader = messageContainer.querySelector('.loading-dots');
                        if (loader && (typeof delta === 'string' && delta.length > 0)) {
                            loader.remove();
                        }

                        if (typeof delta === 'string' && delta.length > 0) {

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
                // (修正) 如果是 [DONE]，跳出外层循环
                if (chunk.includes('data: [DONE]')) break;
            }
            if (chunk.includes('data: [DONE]')) break;
        }
        finalizeStream(); // 处理流在 [DONE] 之前结束的情况
    } catch (e) {
        console.error("Stream processing error:", e);
        finalizeStream(); // 异常时也尝试最终化
        toast('连接中断', 'warning');
    }
}
// --- 响应结束 ---