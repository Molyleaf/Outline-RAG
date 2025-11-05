// app/static/js/main.js
avatar.addEventListener('click', () => {
    // 使用 toggle class 切换
    menu.classList.toggle('visible');
});
// 初始化主题菜单选中态 + 点击切换保存
(function initThemeMenu(){
    const saved = localStorage.getItem('theme') || 'system';
    function applyActive() {
        themeRadios.forEach(r => {
            r.classList.toggle('active', r.dataset.theme === (localStorage.getItem('theme') || 'system'));
        });
    }
    // 应用到根节点
    document.documentElement.setAttribute('data-theme', (saved === 'light' || saved === 'dark') ? saved : 'system');
    applyActive();
    themeRadios.forEach(r => {
        r.addEventListener('click', (e) => { // 'e' 在这里是无害的
            const t = r.dataset.theme;
            localStorage.setItem('theme', t);
            document.documentElement.setAttribute('data-theme', (t === 'light' || t === 'dark') ? t : 'system');
            applyActive();
            toast('已切换为' + (t === 'system' ? '系统' : t === 'light' ? '浅色' : '深色') + '主题', 'success', 1800);
            // 点击后关闭菜单
            menu.classList.remove('visible');
        });
    });
})();

// 自动增高：输入框随输入自适应，最高为屏幕高度的 20%
(function initAutoResize() {
    function applyMax() {
        INPUT_MAX_PX = Math.floor(window.innerHeight * 0.2);
        qEl.style.maxHeight = INPUT_MAX_PX + 'px';
    }
    function autoresize() {
        // 先重置高度以便计算 scrollHeight
        qEl.style.height = 'auto';
        // 在最大高度限制内自适应
        const next = Math.min(qEl.scrollHeight, INPUT_MAX_PX);
        qEl.style.height = next + 'px';
        // 当达到上限时允许滚动，未达上限时不出现滚动条
        qEl.style.overflowY = (qEl.scrollHeight > INPUT_MAX_PX) ? 'auto' : 'hidden';
    }
    applyMax();
    // 初始一次（比如有占位文本或默认值时）
    autoresize();
    // 事件绑定
    qEl.addEventListener('input', autoresize);
    // 窗口尺寸变化时更新上限并重新计算
    window.addEventListener('resize', () => { applyMax(); autoresize(); });
})();

document.addEventListener('click', (e) => {
    // 点击菜单外区域关闭
    if (!avatar.contains(e.target) && !menu.contains(e.target)) menu.classList.remove('visible');
});
refreshAll.addEventListener('click', async (e) => {
    e.preventDefault();
    const r = await api('/chat/update/all', {method: 'POST'});

    if (r && r.ok) {
        toast('已开始全量刷新', 'primary', 2500);
        const poll = setInterval(async () => {
            const data = await api('/chat/api/refresh/status');
            if (!data) { // api() 返回 null 代表网络或认证失败
                clearInterval(poll);
                return;
            }
            if (data.status === 'success') {
                clearInterval(poll);
                toast(data.message || '全量刷新完成', 'success', 4000);
                console.log('全量刷新完成:', data.message);
            } else if (data.status === 'error') {
                clearInterval(poll);
                toast(data.message || '刷新失败', 'danger');
                console.error('全量刷新失败:', data.message);
            }
            // 若状态是 'running' 或 'idle'，则继续轮询
        }, 3000);
    } else if (r && r.error) {
        toast(r.error, 'warning');
    } else {
        toast('启动刷新失败', 'danger');
    }
});
fileInput.addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const form = new FormData();
    form.append('file', f);
    const res = await fetch('/chat/api/upload', { method: 'POST', body: form, credentials: 'include' });
    if (res.ok) toast('上传成功，已加入索引', 'success'); else toast('上传失败', 'danger');
    e.target.value = '';
});

// “新建对话”仅跳转到 /chat，不创建 ID；等待首次发送时再创建并替换 URL
newConvBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    // 清空当前对话上下文与消息区
    currentConvId = null;
    chatEl.innerHTML = '';
    // 确保问候语节点存在则插回去再显示（避免被清空后无法展示）
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

    // 使用 History API 保持在 /chat
    try { history.pushState(null, '', '/chat'); } catch (_) { location.href = '/chat'; return; }

    // 更新侧边栏高亮
    document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));

    // 窄屏下新建完成后自动关闭侧边栏
    if (window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});

// 监听浏览器前进后退，保持 currentConvId 与视图同步（pjax 式体验）
window.addEventListener('popstate', () => {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    currentConvId = m ? m[1] : null;
    chatEl.innerHTML = '';

    // 更新侧边栏高亮
    document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
    if (currentConvId) {
        // 使用 data-id 选择器
        const activeRow = Array.from(convsEl.querySelectorAll('.conv')).find(r => r.dataset.id === currentConvId);
        if (activeRow) activeRow.classList.add('active');
    }

    // 无会话则显示问候语
    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = currentConvId ? 'none' : 'block';
    // 有会话则异步加载消息
    if (currentConvId) {
        loadMessages();
    } else {
        // 确保在 /chat 路径时显示问候语
        loadMessages();
    }
});

sendBtn.addEventListener('click', sendQuestion);
qEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendQuestion();
    }
});


(async function init() {
    function setupTopbarActions() {
        const actionsContainer = document.querySelector('.topbar .actions');
        if (!actionsContainer) return;

        const paramSliderHtml = (label, value, max, step) =>
            '<div class="param-slider">' +
            '<label><span>' + label + '</span><input type="number" class="param-input" value="' + value + '" step="' + step + '" max="' + max + '"></label>' +
            '<input type="range" class="param-range" value="' + value + '" min="0" max="' + max + '" step="' + step + '">' +
            '</div>';

        const uploadLabel = actionsContainer.querySelector('label.upload');
        const uploadSpan = uploadLabel ? uploadLabel.querySelector('span.btn') : null;
        if (uploadSpan) {
            uploadSpan.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>';
            uploadSpan.style.width = '40px';
            uploadSpan.style.height = '40px';
            uploadSpan.style.borderRadius = '50%';
            uploadSpan.style.padding = '0';
            uploadSpan.style.display = 'inline-flex';
            uploadSpan.style.alignItems = 'center';
            uploadSpan.style.justifyContent = 'center';
        }

        function updateModelButtonLook(modelId, btnElement) {
            // (新) 处理没有可用模型的情况
            if (!modelId || !MODELS[modelId]) {
                btnElement.innerHTML = '?';
                btnElement.title = '无可用模型';
                return;
            }
            const modelConf = MODELS[modelId] || {};
            let iconHtml;
            const altTextValue = modelConf.name || 'Model';
            const iconSrc = modelConf.icon || '';

            if (modelId.includes('moonshotai')) {
                btnElement.classList.add('moonshot-dark');
                iconHtml = '<img src="' + iconSrc + '" alt="' + altTextValue + '" style="width:38px;height:38px;border-radius:50%;padding: 0;">';
            } else {
                btnElement.classList.remove('moonshot-dark');
                iconHtml = '<img src="' + iconSrc + '" alt="' + altTextValue + '" style="width:38px;height:38px;border-radius:50%;background-color: white;padding: 3px;">';
            }
            btnElement.innerHTML = iconHtml;
        }

        const modelBtn = document.createElement('button');
        modelBtn.className = 'btn tonal';
        updateModelButtonLook(currentModelId, modelBtn);

        const tempBtn = document.createElement('button');
        tempBtn.className = 'btn tonal';
        tempBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24"><path fill="currentColor" d="M12 13.25a3.25 3.25 0 1 0 0-6.5a3.25 3.25 0 0 0 0 6.5M13.5 4.636a.75.75 0 0 1-.75.75a4.75 4.75 0 0 0 0 9.228a.75.75 0 0 1 0 1.5a6.25 6.25 0 0 1 0-12.228a.75.75 0 0 1 .75.75M12 1.25a.75.75 0 0 1 .75.75v.255a.75.75 0 0 1-1.5 0V2a.75.75 0 0 1 .75-.75M12 20.25a.75.75 0 0 1 .75.75v.255a.75.75 0 0 1-1.5 0V21a.75.75 0 0 1 .75-.75m-6.79-2.54a.75.75 0 1 1-1.06-1.06l.176-.177a.75.75 0 0 1 1.06 1.06zm12.52 0a.75.75 0 1 1 1.06 1.06l-.176.177a.75.75 0 0 1-1.06-1.06z"/></svg>';
        tempBtn.title = 'Temperature: ' + currentTemperature;

        const topPBtn = document.createElement('button');
        topPBtn.className = 'btn tonal';
        topPBtn.innerHTML = '<b>P</b>';
        topPBtn.title = 'Top-P: ' + currentTopP;

        [modelBtn, tempBtn, topPBtn].forEach(btn => {
            btn.style.width = '40px';
            btn.style.height = '40px';
            btn.style.borderRadius = '50%';
            btn.style.padding = '0';
        });

        // 插入新按钮到上传按钮之前
        if (uploadLabel) {
            actionsContainer.insertBefore(modelBtn, uploadLabel);
            actionsContainer.insertBefore(tempBtn, uploadLabel);
            actionsContainer.insertBefore(topPBtn, uploadLabel);
        }

        const mobileModelMenuHtml = () =>
            '<div class="mobile-sheet-group">' +
            '<div class="mobile-sheet-label">模型</div>' +
            '<div class="model-menu mobile">' +
            (Object.keys(MODELS).length > 0 ?
                    Object.entries(MODELS).map(([id, m]) =>
                        '<div class="model-item ' + (id === currentModelId ? 'active' : '') + '" data-id="' + id + '">' +
                        '<img src="' + m.icon + '" alt="' + m.name + '"><span>' + m.name + '</span>' +
                        '</div>'
                    ).join('') :
                    '<div class="popover-placeholder">无可用模型</div>'
            ) +
            '</div>' +
            '</div>' +
            '<div class="mobile-sheet-group">' +
            paramSliderHtml('Temperature', currentTemperature, 2, 0.05) +
            '</div>' +
            '<div class="mobile-sheet-group">' +
            paramSliderHtml('Top-P', currentTopP, 2, 0.05) +
            '</div>';

        // 弹窗逻辑
        function createPopover(btn, contentHtml, onOpen) {
            const pop = document.createElement('div');
            pop.className = 'toolbar-popover';
            pop.innerHTML = contentHtml;
            document.body.appendChild(pop);

            btn.addEventListener('click', (e) => {
                e.stopPropagation();

                // 移动端使用自定义底部弹出
                if (window.innerWidth <= 768 && (btn === tempBtn || btn === topPBtn || btn === modelBtn)) {

                    const fullMobileHtml = mobileModelMenuHtml();
                    showMobileSheet(fullMobileHtml, '模型设置');

                    // --- 动态绑定所有事件 ---

                    // 1. 绑定模型切换
                    mobileSheetContent.querySelectorAll('.model-item').forEach(item => {
                        item.addEventListener('click', () => {
                            currentModelId = item.dataset.id;
                            localStorage.setItem('chat_model', currentModelId);
                            const modelConf = MODELS[currentModelId];
                            currentTemperature = modelConf.temp;
                            currentTopP = modelConf.top_p;

                            updateModelButtonLook(currentModelId, modelBtn);
                            tempBtn.title = 'Temperature: ' + currentTemperature;
                            topPBtn.title = 'Top-P: ' + currentTopP;

                            hideMobileSheet(); // 点击后关闭
                        });
                    });

                    // 2. 绑定 Temp slider
                    const tempSliderBox = mobileSheetContent.querySelector('.mobile-sheet-group:nth-of-type(2) .param-slider');
                    if (tempSliderBox) {
                        setupSlider(tempSliderBox, (val) => {
                            currentTemperature = val;
                        }, tempBtn, 'Temperature');
                    }

                    // 3. 绑定 Top-P slider
                    const topPSliderBox = mobileSheetContent.querySelector('.mobile-sheet-group:nth-of-type(3) .param-slider');
                    if (topPSliderBox) {
                        setupSlider(topPSliderBox, (val) => {
                            currentTopP = val;
                        }, topPBtn, 'Top-P');
                    }

                    return; // 移动端逻辑结束
                }

                // --- 桌面端 popover 逻辑 ---
                const allPops = document.querySelectorAll('.toolbar-popover');
                // 检查 class
                const wasOpen = pop.classList.contains('visible');

                // 先隐藏所有弹窗
                allPops.forEach(p => { p.classList.remove('visible'); });

                // 如果当前弹窗不是打开状态，则显示它
                if (!wasOpen) {
                    const rect = btn.getBoundingClientRect();
                    // 定位在触发按钮的下方，并对齐右侧
                    pop.style.top = rect.bottom + 8 + 'px';
                    pop.style.left = 'auto';
                    pop.style.right = (window.innerWidth - rect.right) + 'px';
                    pop.style.transform = ''; // 确保没有遗留的 transform

                    pop.classList.add('visible'); // 使用 classList
                    if (onOpen) onOpen(pop);
                }
            });
            return pop;
        }

        const desktopModelMenuHtml =
            (Object.keys(MODELS).length > 0 ?
                    '<div class="model-menu">' + Object.entries(MODELS).map(([id, m]) =>
                        '<div class="model-item ' + (id === currentModelId ? 'active' : '') + '" data-id="' + id + '">' +
                        '<img src="' + m.icon + '" alt="' + m.name + '"><span>' + m.name + '</span>' +
                        '</div>'
                    ).join('') +
                    '</div>' :
                    '<div class="popover-placeholder">无可用模型</div>'
            ) +
            '<div class="popover-divider"></div>' +
            paramSliderHtml('Temperature', currentTemperature, 2, 0.05) +
            '<div class="popover-divider"></div>' +
            paramSliderHtml('Top-P', currentTopP, 2, 0.05);

        tempBtn.style.display = 'none';
        topPBtn.style.display = 'none';

        const modelPop = createPopover(modelBtn, desktopModelMenuHtml, (pop) => {
            // 确保打开时滑块状态同步
            const sliders = pop.querySelectorAll('.param-slider');
            if (sliders.length >= 2) {
                const tempInput = sliders[0].querySelector('.param-input');
                const tempRange = sliders[0].querySelector('.param-range');
                const topPInput = sliders[1].querySelector('.param-input');
                const topPRange = sliders[1].querySelector('.param-range');

                if (tempInput) tempInput.value = currentTemperature.toFixed(2);
                if (tempRange) tempRange.value = currentTemperature;
                if (topPInput) topPInput.value = currentTopP.toFixed(2);
                if (topPRange) topPRange.value = currentTopP;
            }

            // 更新 active 状态
            pop.querySelectorAll('.model-item').forEach(item => {
                item.classList.toggle('active', item.dataset.id === currentModelId);
            });
        });

        // 绑定桌面端模型切换
        modelPop.querySelectorAll('.model-item').forEach(item => {
            item.addEventListener('click', () => {
                currentModelId = item.dataset.id;
                localStorage.setItem('chat_model', currentModelId);
                const modelConf = MODELS[currentModelId];
                currentTemperature = modelConf.temp;
                currentTopP = modelConf.top_p;

                updateModelButtonLook(currentModelId, modelBtn);
                tempBtn.title = 'Temperature: ' + currentTemperature;
                topPBtn.title = 'Top-P: ' + currentTopP;

                // 更新 active 状态并关闭
                modelPop.querySelectorAll('.model-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                modelPop.classList.remove('visible'); // 使用 classList
            });
        });

        function setupSlider(pop, stateUpdater, btn, titlePrefix) {
            // 检查 pop 是否为 null
            if (!pop) {
                console.error('setupSlider received null element. This might be a selector error.');
                return;
            }
            const input = pop.querySelector('.param-input');
            const range = pop.querySelector('.param-range');

            // 检查 input 和 range 是否为 null
            if (!input || !range) {
                console.error('Slider input or range not found inside', pop);
                return;
            }

            const update = (val) => {
                const num = parseFloat(val);
                if (!isNaN(num)) {
                    stateUpdater(num);
                    input.value = num.toFixed(2);
                    range.value = num;
                    btn.title = titlePrefix + ': ' + num.toFixed(2);
                }
            };
            input.addEventListener('input', (e) => update(e.target.value));
            range.addEventListener('input', (e) => update(e.target.value));
        }

        // 绑定桌面端 Slider
        const desktopSliders = modelPop.querySelectorAll('.param-slider');
        if (desktopSliders.length >= 2) {
            setupSlider(desktopSliders[0], (val) => currentTemperature = val, tempBtn, 'Temperature');
            setupSlider(desktopSliders[1], (val) => currentTopP = val, topPBtn, 'Top-P');
        }


        document.addEventListener('click', () => {
            // 使用 classList
            document.querySelectorAll('.toolbar-popover').forEach(p => p.classList.remove('visible'));
        });
    }

    // (新) setupTopbarActions 必须在 loadUser 之后调用
    // setupTopbarActions();

    // 顺序：先获取用户，再会话；完成后若有当前会话再加载消息
    (async () => {
        try {
            await loadUser();
            // (新) 确保在 loadUser 之后调用
            setupTopbarActions();
        } catch(_) {}

        await loadConvs();
        // 无会话 ID 时确保问候语显示（包括直接打开 /chat 或新建对话后）
        const greet = document.getElementById('greeting');
        if (!currentConvId && greet) {
            greet.style.display = 'block';
        }
        if (currentConvId) {
            try { await loadMessages(); } catch(_) {}
        }
    })();
})();

// 移动端侧边栏开关逻辑
if (hamburger) {
    hamburger.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        appRoot?.classList.toggle('sidebar-open');
    });
}
if (sidebarVeil) {
    sidebarVeil.addEventListener('click', () => {
        appRoot?.classList.remove('sidebar-open');
    });
}
// 在窄屏导航到会话后自动关闭侧栏
convsEl.addEventListener('click', (e) => {
    // 确保点击的是 .conv 自身或其子元素，但不是菜单按钮
    const convRow = e.target.closest('.conv');
    const menuBtn = e.target.closest('.conv-menu');
    const menuPop = e.target.closest('.conv-menu-pop');

    if (convRow && !menuBtn && !menuPop && window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});