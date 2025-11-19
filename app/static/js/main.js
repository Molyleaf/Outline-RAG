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
            btn.style.width = '32px';
            btn.style.height = '32px';
            btn.style.borderRadius = '50%';
            btn.style.padding = '0';
        });

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

        function createPopover(btn, contentHtml, onOpen) {
            const pop = document.createElement('div');
            pop.className = 'toolbar-popover';
            pop.innerHTML = contentHtml;
            document.body.appendChild(pop);

            btn.addEventListener('click', (e) => {
                e.stopPropagation();

                if (window.innerWidth <= 768 && (btn === tempBtn || btn === topPBtn || btn === modelBtn)) {

                    const fullMobileHtml = mobileModelMenuHtml();
                    showMobileSheet(fullMobileHtml, '模型设置');

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

                            hideMobileSheet();
                        });
                    });

                    const tempSliderBox = mobileSheetContent.querySelector('.mobile-sheet-group:nth-of-type(2) .param-slider');
                    if (tempSliderBox) {
                        setupSlider(tempSliderBox, (val) => {
                            currentTemperature = val;
                        }, tempBtn, 'Temperature');
                    }

                    const topPSliderBox = mobileSheetContent.querySelector('.mobile-sheet-group:nth-of-type(3) .param-slider');
                    if (topPSliderBox) {
                        setupSlider(topPSliderBox, (val) => {
                            currentTopP = val;
                        }, topPBtn, 'Top-P');
                    }

                    return;
                }

                const allPops = document.querySelectorAll('.toolbar-popover');
                const wasOpen = pop.classList.contains('visible');

                allPops.forEach(p => { p.classList.remove('visible'); });

                if (!wasOpen) {
                    const rect = btn.getBoundingClientRect();
                    pop.style.top = rect.bottom + 8 + 'px';
                    pop.style.left = 'auto';
                    pop.style.right = (window.innerWidth - rect.right) + 'px';
                    pop.style.transform = '';

                    pop.classList.add('visible');
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

            pop.querySelectorAll('.model-item').forEach(item => {
                item.classList.toggle('active', item.dataset.id === currentModelId);
            });
        });

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

                modelPop.querySelectorAll('.model-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                modelPop.classList.remove('visible');
            });
        });

        function setupSlider(pop, stateUpdater, btn, titlePrefix) {
            if (!pop) {
                console.error('setupSlider received null element. This might be a selector error.');
                return;
            }
            const input = pop.querySelector('.param-input');
            const range = pop.querySelector('.param-range');

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

        const desktopSliders = modelPop.querySelectorAll('.param-slider');
        if (desktopSliders.length >= 2) {
            setupSlider(desktopSliders[0], (val) => currentTemperature = val, tempBtn, 'Temperature');
            setupSlider(desktopSliders[1], (val) => currentTopP = val, topPBtn, 'Top-P');
        }


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