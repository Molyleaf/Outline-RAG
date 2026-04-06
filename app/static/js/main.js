avatar.addEventListener('click', () => {
    menu.classList.toggle('visible');
});

(function initThemeMenu(){
    const themeRadios = Array.from(document.querySelectorAll('.menu .menu-radio'));
    const lightTheme = document.getElementById('hljs-light-theme');
    const darkTheme = document.getElementById('hljs-dark-theme');

    /**
     * 根据当前主题切换 Highlight.js 的样式表
     * @param {string} theme - 'system', 'light', 'dark'
     */
    function updateHljsTheme(theme) {
        if (!lightTheme || !darkTheme) return;

        const wantsDark = (theme === 'dark') ||
            (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);

        if (wantsDark) {
            lightTheme.disabled = true;
            darkTheme.disabled = false;
        } else {
            lightTheme.disabled = false;
            darkTheme.disabled = true;
        }
    }

    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        const currentTheme = localStorage.getItem('theme') || 'system';
        if (currentTheme === 'system') {
            document.documentElement.setAttribute('data-theme', 'system');
            updateHljsTheme('system');
        }
    });

    const saved = localStorage.getItem('theme') || 'system';

    function applyActive() {
        themeRadios.forEach(r => {
            r.classList.toggle('active', r.dataset.theme === (localStorage.getItem('theme') || 'system'));
        });
    }

    document.documentElement.setAttribute('data-theme', (saved === 'light' || saved === 'dark') ? saved : 'system');

    updateHljsTheme(saved);

    applyActive();

    themeRadios.forEach(r => {
        r.addEventListener('click', (e) => {
            const t = r.dataset.theme;
            localStorage.setItem('theme', t);
            document.documentElement.setAttribute('data-theme', (t === 'light' || t === 'dark') ? t : 'system');

            updateHljsTheme(t);

            applyActive();
            toast('已切换为' + (t === 'system' ? '系统' : t === 'light' ? '浅色' : '深色') + '主题', 'success', 1800);
            menu.classList.remove('visible');
        });
    });
})();

(function initAutoResize() {
    function applyMax() {
        INPUT_MAX_PX = Math.floor(window.innerHeight * 0.2);
        qEl.style.maxHeight = INPUT_MAX_PX + 'px';
    }
    function autoresize() {
        qEl.style.height = 'auto';
        const next = Math.min(qEl.scrollHeight, INPUT_MAX_PX);
        qEl.style.height = next + 'px';
        qEl.style.overflowY = (qEl.scrollHeight > INPUT_MAX_PX) ? 'auto' : 'hidden';
    }
    applyMax();
    autoresize();
    qEl.addEventListener('input', autoresize);
    window.addEventListener('resize', () => { applyMax(); autoresize(); });
})();

document.addEventListener('click', (e) => {
    if (!avatar.contains(e.target) && !menu.contains(e.target)) menu.classList.remove('visible');
});
refreshAll.addEventListener('click', async (e) => {
    e.preventDefault();
    const r = await api('/chat/update/all', {method: 'POST'});

    if (r && r.ok) {
        toast('已开始全量刷新', 'primary', 2500);
        const poll = setInterval(async () => {
            const data = await api('/chat/api/refresh/status');
            if (!data) {
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

newConvBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    currentConvId = null;
    chatEl.innerHTML = '';

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

        // [修复] 使用事件委托绑定，确保点击生效
        greet.addEventListener('click', (evt) => {
            const chip = evt.target.closest('.chip');
            if (chip) {
                evt.preventDefault();
                if (qEl) {
                    qEl.value = chip.textContent.trim();
                    qEl.focus();
                    // 触发自动高度调整
                    qEl.dispatchEvent(new Event('input'));
                }
            }
        });
    }

    const greetTitle = greet.querySelector('.greet-title');
    if (greetTitle) {
        const name = (userInfo?.name || userInfo?.username || '').trim();
        greetTitle.textContent = name ? '你好，' + name + '！' : '你好！';
    }
    greet.style.display = 'block';

    try { history.pushState(null, '', '/chat'); } catch (_) { location.href = '/chat'; return; }

    document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));

    if (window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});

window.addEventListener('popstate', () => {
    const m = location.pathname.replace(/\/+$/,'').match(/^\/chat\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$/);
    currentConvId = m ? m[1] : null;
    chatEl.innerHTML = '';

    document.querySelectorAll('.conv.active').forEach(n => n.classList.remove('active'));
    if (currentConvId) {
        const activeRow = Array.from(convsEl.querySelectorAll('.conv')).find(r => r.dataset.id === currentConvId);
        if (activeRow) activeRow.classList.add('active');
    }

    const greet = document.getElementById('greeting');
    if (greet) greet.style.display = currentConvId ? 'none' : 'block';
    if (currentConvId) {
        loadMessages();
    } else {
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
    /* 在 init 开始时调用预加载 */
    preloadShoelaceComponents();
    function setupTopbarActions() {
        const actionsContainer = document.querySelector('.topbar .actions');
        if (!actionsContainer) return;

        const paramSliderHtml = (label, value, max, step) =>
            '<div class="param-slider">' +
            '<label><span>' + label + '</span><input type="number" class="param-input" value="' + value + '" step="' + step + '" max="' + max + '"></label>' +
            '<input type="range" class="param-range" value="' + value + '" min="0" max="' + max + '" step="' + step + '">' +
            '</div>';

        const escapeAttr = (value) => String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/"/g, '&quot;');

        const renderModeItem = (mode) =>
            '<div class="mode-item ' + (mode.id === currentResponseMode ? 'active' : '') + '" data-mode="' + mode.id + '">' +
            '<div class="mode-item-title">' + mode.name + '</div>' +
            '<div class="mode-item-desc">' + mode.description + '</div>' +
            '</div>';

        const renderModelItem = ([id, model]) =>
            '<div class="model-item ' + (id === currentModelId ? 'active' : '') + '" data-id="' + id + '" data-custom="' + (model.is_custom ? 'true' : 'false') + '">' +
            '<img src="' + model.icon + '" alt="' + model.name + '">' +
            '<span>' + model.name + '</span>' +
            (model.is_custom ? '<span class="model-badge ' + (model.configured ? 'configured' : 'pending') + '">' + (model.configured ? '已配置' : '配置') + '</span>' : '') +
            '</div>';

        const uploadLabel = actionsContainer.querySelector('label.upload');
        const uploadSpan = uploadLabel ? uploadLabel.querySelector('span.btn') : null;
        if (uploadSpan) {
            uploadSpan.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>';
            uploadSpan.style.width = '32px';
            uploadSpan.style.height = '32px';
            uploadSpan.style.borderRadius = '50%';
            uploadSpan.style.padding = '0';
            uploadSpan.style.display = 'inline-flex';
            uploadSpan.style.alignItems = 'center';
            uploadSpan.style.justifyContent = 'center';
        }

        function getModeIcon(modeId) {
            if (modeId === RESPONSE_MODES.copy_prompt.id) {
                return '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';
            }
            return '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
        }

        function updateModeButtonLook(modeId, btnElement) {
            const mode = RESPONSE_MODES[modeId] || RESPONSE_MODES.answer;
            btnElement.innerHTML = getModeIcon(mode.id);
            btnElement.title = '模式: ' + mode.name;
            btnElement.dataset.mode = mode.id;
        }

        function updateModelButtonLook(modelId, btnElement) {
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
                iconHtml = '<img src="' + iconSrc + '" alt="' + altTextValue + '" style="width:32px;height:32px;border-radius:50%;padding: 0;">';
            } else {
                btnElement.classList.remove('moonshot-dark');
                iconHtml = '<img src="' + iconSrc + '" alt="' + altTextValue + '" style="width:32px;height:32px;border-radius:50%;background-color: white;padding: 2px;">';
            }
            btnElement.innerHTML = iconHtml;
            btnElement.title = '模型: ' + getModelLabel(modelId);
        }

        function applyModelSelection(modelId) {
            currentModelId = modelId;
            localStorage.setItem('chat_model', currentModelId);
            const modelConf = MODELS[currentModelId] || {};
            if (typeof modelConf.temp === 'number') currentTemperature = modelConf.temp;
            if (typeof modelConf.top_p === 'number') currentTopP = modelConf.top_p;
            updateModelButtonLook(currentModelId, modelBtn);
        }

        function renderModeMenuHtml() {
            return '<div class="mode-menu">' + Object.values(RESPONSE_MODES).map(renderModeItem).join('') + '</div>';
        }

        function renderModelMenuHtml() {
            return (
                (Object.keys(MODELS).length > 0 ?
                    '<div class="model-menu">' + Object.entries(MODELS).map(renderModelItem).join('') + '</div>' :
                    '<div class="popover-placeholder">无可用模型</div>'
                ) +
                '<div class="popover-divider"></div>' +
                paramSliderHtml('Temperature', currentTemperature, 2, 0.05) +
                '<div class="popover-divider"></div>' +
                paramSliderHtml('Top-P', currentTopP, 2, 0.05)
            );
        }

        const modeBtn = document.createElement('button');
        modeBtn.className = 'btn tonal';
        updateModeButtonLook(currentResponseMode, modeBtn);

        const modelBtn = document.createElement('button');
        modelBtn.className = 'btn tonal';
        updateModelButtonLook(currentModelId, modelBtn);

        [modeBtn, modelBtn].forEach(btn => {
            btn.style.width = '32px';
            btn.style.height = '32px';
            btn.style.borderRadius = '50%';
            btn.style.padding = '0';
        });

        if (uploadLabel) {
            actionsContainer.insertBefore(modeBtn, uploadLabel);
            actionsContainer.insertBefore(modelBtn, uploadLabel);
        }

        const modelPop = document.createElement('div');
        modelPop.className = 'toolbar-popover';
        document.body.appendChild(modelPop);

        const modePop = document.createElement('div');
        modePop.className = 'toolbar-popover';
        document.body.appendChild(modePop);

        function positionPopover(btn, pop) {
            const rect = btn.getBoundingClientRect();
            pop.style.top = rect.bottom + 8 + 'px';
            pop.style.left = 'auto';
            pop.style.right = (window.innerWidth - rect.right) + 'px';
            pop.style.transform = '';
        }

        async function openCustomOpenAIConfigDialog(selectAfterSave = true) {
            return new Promise(resolve => {
                const dlg = document.createElement('sl-dialog');
                dlg.label = customOpenAIConfig?.configured ? '编辑自定义 OpenAI' : '配置自定义 OpenAI';
                dlg.innerHTML =
                    '<div class="custom-model-form">' +
                    '<sl-input class="endpoint" label="Endpoint" placeholder="https://example.com/v1" value="' + escapeAttr(customOpenAIConfig?.endpoint) + '"></sl-input>' +
                    '<sl-input class="model-name" label="模型名" placeholder="gpt-4o-mini" value="' + escapeAttr(customOpenAIConfig?.model_name) + '"></sl-input>' +
                    '<sl-input class="api-key" type="password" label="API Key" placeholder="' + (customOpenAIConfig?.configured ? '留空表示沿用已保存的 Key' : 'sk-...') + '"></sl-input>' +
                    '<div class="custom-model-hint">API Key 仅保存到当前用户私有配置中。</div>' +
                    '</div>' +
                    '<div slot="footer" style="display:flex;gap:8px;justify-content:flex-end">' +
                    '<sl-button class="cancel" variant="neutral">取消</sl-button>' +
                    '<sl-button class="ok" variant="primary">保存并使用</sl-button>' +
                    '</div>';
                document.body.appendChild(dlg);

                const endpointInput = dlg.querySelector('.endpoint');
                const modelInput = dlg.querySelector('.model-name');
                const apiKeyInput = dlg.querySelector('.api-key');
                const okBtn = dlg.querySelector('.ok');
                const cancelBtn = dlg.querySelector('.cancel');

                const hideDialog = () => {
                    if (typeof dlg.hide === 'function') dlg.hide(); else dlg.removeAttribute('open');
                };

                dlg.addEventListener('sl-after-hide', () => dlg.remove());
                cancelBtn.addEventListener('click', () => {
                    hideDialog();
                    resolve(false);
                });

                okBtn.addEventListener('click', async () => {
                    const endpoint = (endpointInput.value || '').trim();
                    const modelName = (modelInput.value || '').trim();
                    const apiKey = (apiKeyInput.value || '').trim();
                    if (!endpoint || !modelName) {
                        toast('Endpoint 和模型名不能为空', 'warning');
                        return;
                    }

                    okBtn.loading = true;
                    const res = await api('/chat/api/user-custom-openai', {
                        method: 'POST',
                        body: JSON.stringify({
                            endpoint,
                            model_name: modelName,
                            api_key: apiKey
                        })
                    });
                    okBtn.loading = false;

                    if (!res || !res.ok || !res.model) {
                        toast(res?.detail || res?.error || '保存失败', 'danger');
                        return;
                    }

                    customOpenAIConfig = res.custom_openai || { configured: true, endpoint, model_name: modelName };
                    MODELS[res.model.id] = res.model;
                    if (selectAfterSave) applyModelSelection(res.model.id);
                    updateModelButtonLook(currentModelId, modelBtn);
                    hideDialog();
                    toast('已保存自定义 OpenAI 配置', 'success', 1800);
                    resolve(true);
                });

                if (typeof dlg.show === 'function') dlg.show(); else dlg.setAttribute('open', '');
            });
        }

        function setupSlider(box, stateUpdater) {
            if (!box) return;
            const input = box.querySelector('.param-input');
            const range = box.querySelector('.param-range');
            if (!input || !range) return;

            const update = (val) => {
                const num = parseFloat(val);
                if (Number.isNaN(num)) return;
                stateUpdater(num);
                input.value = num.toFixed(2);
                range.value = String(num);
            };

            input.addEventListener('input', (e) => update(e.target.value));
            range.addEventListener('input', (e) => update(e.target.value));
        }

        function bindModelMenu(container, closeMenu) {
            container.querySelectorAll('.model-item').forEach(item => {
                item.addEventListener('click', async () => {
                    if (item.dataset.custom === 'true') {
                        closeMenu();
                        await openCustomOpenAIConfigDialog(true);
                        return;
                    }
                    applyModelSelection(item.dataset.id);
                    closeMenu();
                });
            });

            const sliders = container.querySelectorAll('.param-slider');
            if (sliders.length >= 2) {
                setupSlider(sliders[0], (val) => currentTemperature = val);
                setupSlider(sliders[1], (val) => currentTopP = val);
            }
        }

        function openModeMobileSheet() {
            const html =
                '<div class="mobile-sheet-group">' +
                '<div class="mobile-sheet-label">模式</div>' +
                Object.values(RESPONSE_MODES).map(mode =>
                    '<div class="mobile-menu-item mode-mobile-item ' + (mode.id === currentResponseMode ? 'active' : '') + '" data-mode="' + mode.id + '">' +
                    '<div class="mode-item-title">' + mode.name + '</div>' +
                    '<div class="mode-item-desc">' + mode.description + '</div>' +
                    '</div>'
                ).join('') +
                '</div>';
            showMobileSheet(html, '提问模式');
            mobileSheetContent.querySelectorAll('.mode-mobile-item').forEach(item => {
                item.addEventListener('click', () => {
                    currentResponseMode = item.dataset.mode;
                    localStorage.setItem('chat_response_mode', currentResponseMode);
                    updateModeButtonLook(currentResponseMode, modeBtn);
                    hideMobileSheet();
                });
            });
        }

        function openModelMobileSheet() {
            const html =
                '<div class="mobile-sheet-group">' +
                '<div class="mobile-sheet-label">模型</div>' +
                '<div class="model-menu mobile">' +
                (Object.keys(MODELS).length > 0 ?
                    Object.entries(MODELS).map(renderModelItem).join('') :
                    '<div class="popover-placeholder">无可用模型</div>'
                ) +
                '</div>' +
                '</div>' +
                '<div class="mobile-sheet-group">' + paramSliderHtml('Temperature', currentTemperature, 2, 0.05) + '</div>' +
                '<div class="mobile-sheet-group">' + paramSliderHtml('Top-P', currentTopP, 2, 0.05) + '</div>';
            showMobileSheet(html, '模型设置');
            bindModelMenu(mobileSheetContent, hideMobileSheet);
        }

        function togglePopover(btn, pop, html, binder) {
            const wasOpen = pop.classList.contains('visible');
            document.querySelectorAll('.toolbar-popover.visible').forEach(p => p.classList.remove('visible'));
            if (wasOpen) return;
            pop.innerHTML = html();
            positionPopover(btn, pop);
            pop.classList.add('visible');
            binder(pop);
        }

        modeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.innerWidth <= 768) {
                openModeMobileSheet();
                return;
            }
            togglePopover(modeBtn, modePop, renderModeMenuHtml, (popEl) => {
                popEl.querySelectorAll('.mode-item').forEach(item => {
                    item.addEventListener('click', () => {
                        currentResponseMode = item.dataset.mode;
                        localStorage.setItem('chat_response_mode', currentResponseMode);
                        updateModeButtonLook(currentResponseMode, modeBtn);
                        modePop.classList.remove('visible');
                    });
                });
            });
        });

        modelBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (window.innerWidth <= 768) {
                openModelMobileSheet();
                return;
            }
            togglePopover(modelBtn, modelPop, renderModelMenuHtml, (popEl) => {
                bindModelMenu(popEl, () => modelPop.classList.remove('visible'));
            });
        });

        document.addEventListener('click', () => {
            document.querySelectorAll('.toolbar-popover').forEach(p => p.classList.remove('visible'));
        });
    }

    (async () => {
        try {
            await loadUser();
            setupTopbarActions();
        } catch(_) {}

        await loadConvs();
        const greet = document.getElementById('greeting');
        if (!currentConvId && greet) {
            greet.style.display = 'block';
        }
        if (currentConvId) {
            try { await loadMessages(); } catch(_) {}
        }
    })();
})();

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
convsEl.addEventListener('click', (e) => {
    const convRow = e.target.closest('.conv');
    const menuBtn = e.target.closest('.conv-menu');
    const menuPop = e.target.closest('.conv-menu-pop');

    if (convRow && !menuBtn && !menuPop && window.innerWidth <= 960) {
        appRoot?.classList.remove('sidebar-open');
    }
});
