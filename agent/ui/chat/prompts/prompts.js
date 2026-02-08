(() => {
    const promptState = {
        open: false,
        scope: 'all',
        sort: 'recent',
        q: '',
        manage: false,
        editingId: null,
        prompts: []
    };

    function qs(id) {
        return document.getElementById(id);
    }

    function setPanelOpen(open) {
        const panel = qs('promptPanel');
        if (!panel) return;
        panel.style.display = open ? 'flex' : 'none';
        promptState.open = open;
        if (open) {
            loadPrompts();
        }
    }

    function setActiveTab(target) {
        const tabs = document.querySelectorAll('.prompt-tab');
        tabs.forEach(tab => tab.classList.remove('active'));
        if (target) target.classList.add('active');
    }

    async function loadPrompts() {
        if (!window.API || !API.getPromptTemplates) return;
        try {
            const data = await API.getPromptTemplates(promptState.scope, promptState.sort, promptState.q);
            promptState.prompts = data.prompts || [];
            renderPromptList();
        } catch (err) {
            console.error('加载提示词失败', err);
        }
    }

    function renderPromptList() {
        const list = qs('promptList');
        if (!list) return;
        list.innerHTML = '';
        if (!promptState.prompts.length) {
            const empty = document.createElement('div');
            empty.className = 'prompt-item';
            empty.textContent = '暂无提示词';
            list.appendChild(empty);
            return;
        }
        promptState.prompts.forEach(item => {
            const card = document.createElement('div');
            card.className = 'prompt-item';
            card.dataset.id = item.id;
            card.addEventListener('click', () => handlePromptClick(item));

            const title = document.createElement('div');
            title.className = 'prompt-item-title';
            title.textContent = item.name || '提示词';

            const desc = document.createElement('div');
            desc.className = 'prompt-item-desc';
            desc.textContent = (item.content || '').slice(0, 60);

            card.appendChild(title);
            card.appendChild(desc);

            const canManage = promptState.manage
                && item.owner_id
                && !item.is_official
                && window.chatState
                && window.chatState.userId === item.owner_id;
            if (canManage) {
                const actions = document.createElement('div');
                actions.className = 'prompt-item-actions';

                const editBtn = document.createElement('button');
                editBtn.type = 'button';
                editBtn.textContent = '编辑';
                editBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    openEditor(item);
                });

                const deleteBtn = document.createElement('button');
                deleteBtn.type = 'button';
                deleteBtn.textContent = '删除';
                deleteBtn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    if (!confirm('确认删除该提示词？')) return;
                    await API.deletePromptTemplate(item.id);
                    loadPrompts();
                });

                actions.appendChild(editBtn);
                actions.appendChild(deleteBtn);
                card.appendChild(actions);
            }

            list.appendChild(card);
        });
    }

    function handlePromptClick(item) {
        const input = qs('chatInput');
        if (!input) return;
        const block = `[提示词]\n${item.content || ''}`;
        const current = input.value || '';
        input.value = current ? `${current}\n\n${block}` : block;
        if (window.autoResizeChatInput) {
            window.autoResizeChatInput(input);
        }
        if (window.updateSkillMatches) {
            window.updateSkillMatches(input.value);
        }
        if (API.usePromptTemplate) {
            API.usePromptTemplate(item.id).catch(() => {});
        }
        setPanelOpen(false);
    }

    function toggleManage() {
        promptState.manage = !promptState.manage;
        const btn = qs('promptManageBtn');
        if (btn) btn.textContent = promptState.manage ? '完成' : '管理';
        renderPromptList();
    }

    function openEditor(item = null) {
        const editor = qs('promptEditor');
        if (!editor) return;
        editor.classList.remove('hidden');
        promptState.editingId = item ? item.id : null;
        const title = qs('promptEditorTitle');
        const nameInput = qs('promptNameInput');
        const contentInput = qs('promptContentInput');
        const tagsInput = qs('promptTagsInput');
        if (title) title.textContent = item ? '编辑提示词' : '新建提示词';
        if (nameInput) nameInput.value = item ? item.name || '' : '';
        if (contentInput) contentInput.value = item ? item.content || '' : '';
        if (tagsInput) tagsInput.value = item ? item.tags || '' : '';
    }

    function closeEditor() {
        const editor = qs('promptEditor');
        if (editor) editor.classList.add('hidden');
        promptState.editingId = null;
    }

    async function saveEditor() {
        const nameInput = qs('promptNameInput');
        const contentInput = qs('promptContentInput');
        if (!nameInput || !contentInput) return;
        const payload = {
            name: nameInput.value.trim(),
            content: contentInput.value.trim()
        };
        if (!payload.name || !payload.content) {
            alert('提示词名称和内容不能为空');
            return;
        }
        if (promptState.editingId) {
            await API.updatePromptTemplate(promptState.editingId, payload);
        } else {
            await API.createPromptTemplate(payload);
        }
        closeEditor();
        loadPrompts();
    }

    async function loadPromptPanelTemplate() {
        const wrapper = qs('promptWrapper');
        if (!wrapper) return;
        try {
            const resp = await fetch('/static/chat/prompts/prompts.html');
            if (!resp.ok) throw new Error('加载提示词模板失败');
            const html = await resp.text();
            wrapper.insertAdjacentHTML('beforeend', html);
        } catch (err) {
            console.error('加载提示词模板失败', err);
        }
    }

    function initPromptPanel() {
        const btn = qs('promptBtn');
        const closeBtn = qs('promptCloseBtn');
        const manageBtn = qs('promptManageBtn');
        const addBtn = qs('promptAddInlineBtn');
        const searchInput = qs('promptSearchInput');
        const saveBtn = qs('promptSaveBtn');
        const cancelBtn = qs('promptCancelBtn');

        if (btn) {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                setPanelOpen(!promptState.open);
            });
        }

        if (closeBtn) closeBtn.addEventListener('click', () => setPanelOpen(false));
        if (manageBtn) manageBtn.addEventListener('click', toggleManage);
        if (addBtn) addBtn.addEventListener('click', () => openEditor());
        if (saveBtn) saveBtn.addEventListener('click', saveEditor);
        if (cancelBtn) cancelBtn.addEventListener('click', closeEditor);

        if (searchInput) {
            let timer = null;
            searchInput.addEventListener('input', () => {
                promptState.q = searchInput.value.trim();
                if (timer) clearTimeout(timer);
                timer = setTimeout(loadPrompts, 200);
            });
        }

        document.querySelectorAll('.prompt-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                setActiveTab(tab);
                promptState.scope = tab.dataset.scope || 'all';
                promptState.sort = tab.dataset.sort || 'recent';
                loadPrompts();
            });
        });

        document.addEventListener('click', (e) => {
            const panel = qs('promptPanel');
            const wrapper = panel ? panel.closest('.prompt-wrapper') : null;
            if (!promptState.open) return;
            if (wrapper && !wrapper.contains(e.target)) {
                setPanelOpen(false);
            }
        });
    }

    document.addEventListener('DOMContentLoaded', async () => {
        await loadPromptPanelTemplate();
        initPromptPanel();
    });
})();
