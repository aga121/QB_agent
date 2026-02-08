/**
 * API调用模块
 * 处理与后端的所有API通信
 */

// API基础配置
const API_BASE_URL = '/api/v1';

// 从localStorage获取token
function getToken() {
    return localStorage.getItem('token');
}

// 设置token到localStorage
function setToken(token) {
    localStorage.setItem('token', token);
}

// 清除token
function clearToken() {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
}

// 获取请求头
function getAuthHeaders() {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json'
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

// 通用API请求方法
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(`${API_BASE_URL}${url}`, {
            ...options,
            headers: {
                ...getAuthHeaders(),
                ...options.headers
            }
        });

        const data = await response.json();

        if (!response.ok) {
            // 如果是401错误，可能token过期，清除并跳转登录
            if (response.status === 401) {
                clearToken();
                window.location.href = '/login';
                return;
            }
            throw new Error(data.detail || '请求失败');
        }

        return data;
    } catch (error) {
        console.error('API请求错误:', error);
        throw error;
    }
}

// ==================== 用户认证API ====================

/**
 * 用户登录
 * @param {string} username 用户名
 * @param {string} password 密码
 */
async function login(phone, code) {
    return apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ phone, code })
    });
}

/**
 * 用户登出
 */
async function logout() {
    try {
        const response = await apiRequest('/auth/logout', {
            method: 'POST'
        });
        clearToken();
        return response;
    } catch (error) {
        // 即使登出失败也要清除本地token
        clearToken();
        throw error;
    }
}

/**
 * 用户注册
 * @param {Object} userData 用户数据
 */
async function register(userData) {
    return apiRequest('/auth/register', {
        method: 'POST',
        body: JSON.stringify(userData)
    });
}

/**
 * 获取当前用户信息
 */
async function getCurrentUser() {
    return apiRequest('/user/info');
}

// ==================== 好友和联系人API ====================

/**
 * 获取好友和联系人列表（包含AI智能体）
 */
async function getContactsList() {
    return apiRequest('/friends');
}

/**
 * 发送好友请求
 * @param {string} friendUsername 好友用户名
 */
async function sendFriendRequest(friendUsername) {
    return apiRequest('/friends/request', {
        method: 'POST',
        body: JSON.stringify({ friend_username: friendUsername })
    });
}

/**
 * 获取好友请求列表
 */
async function getFriendRequests() {
    return apiRequest('/friends/requests');
}

/**
 * 处理好友请求
 * @param {string} friendUsername 好友用户名
 * @param {string} action 操作类型：accept 或 reject
 */
async function handleFriendRequest(friendUsername, action) {
    return apiRequest('/friends/action', {
        method: 'POST',
        body: JSON.stringify({
            friend_username: friendUsername,
            action: action
        })
    });
}

// ==================== 智能体API ====================

/**
 * 获取用户的智能体列表
 */
async function getAgentsList() {
    return apiRequest('/chat/agents');
}

/**
 * 新建AI智能体
 * @param {Object} payload { username, system_prompt, work_dir? }
 */
async function createAiAssistant(payload) {
    return apiRequest('/ai_agents', {
        method: 'POST',
        body: JSON.stringify(payload)
    });
}

/**
 * 获取默认AI system_prompt
 * @param {Object} payload { username?, work_dir? }
 */
async function getAiDefaultPrompt(payload) {
    return apiRequest('/ai_agents/default_prompt', {
        method: 'POST',
        body: JSON.stringify(payload || {})
    });
}

/**
 * 初始化用户AI智能体（若已存在则返回列表）
 * @param {string} userId 用户ID
 */
async function initUserAgents(userId) {
    return apiRequest('/chat/agent_init', {
        method: 'POST',
        body: JSON.stringify({ user_id: userId })
    });
}

/**
 * 初始化智能体
 * @param {string} agentId 智能体ID
 */
async function initAgent(agentId) {
    return apiRequest(`/chat/agent/${agentId}/init`, {
        method: 'POST'
    });
}

/**
 * 获取智能体状态
 * @param {string} agentId 智能体ID
 */
async function getAgentStatus(agentId) {
    return apiRequest(`/chat/agent/${agentId}/status`);
}

/**
 * 开始智能体会话
 * @param {string} agentId 智能体ID
 */
async function startAgentSession(agentId) {
    return apiRequest(`/chat/agent/${agentId}/start-session`, {
        method: 'POST'
    });
}

/**
 * 结束智能体会话
 * @param {string} agentId 智能体ID
 */
async function endAgentSession(agentId) {
    return apiRequest(`/chat/agent/${agentId}/end-session`, {
        method: 'POST'
    });
}

// ==================== 聊天接口 ====================

/**
 * 发送单次消息（非流式）
 * @param {Object} payload { ai_agent_id, message, session_id?, message_type?, metadata? }
 */
async function sendChatMessage(payload) {
    return apiRequest('/chat/send', {
        method: 'POST',
        body: JSON.stringify(payload)
    });
}

/**
 * 获取指定会话的全部消息
 * @param {string} sessionId 会话ID
 */
async function getSessionMessages(sessionId) {
    return apiRequest(`/chat/messages/${sessionId}`);
}

/**
 * 按会话增量同步消息
 * @param {string} userId 当前用户ID
 * @param {Object} payload { known_counts, include_inactive?, current_session_id?, limit_per_session? }
 */
async function syncChatMessages(userId, payload) {
    return apiRequest(`/chat/sessions/${userId}/sync`, {
        method: 'POST',
        body: JSON.stringify(payload)
    });
}

/**
 * 获取用户的会话列表
 * @param {string} userId 用户ID
 */
async function getChatSessions(userId) {
    return apiRequest(`/chat/sessions/${userId}`);
}

/**
 * 获取指定会话的工作目录文件列表
 * @param {string} userId 用户ID
 * @param {string} sessionId 会话ID
 */
async function getSessionFiles(userId, sessionId, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/files?${params.toString()}`);
}

/**
 * 读取文件
 */
async function readSessionFile(userId, sessionId, path, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, path, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/file?${params.toString()}`);
}

/**
 * 创建/写入文件
 */
async function writeSessionFile(userId, sessionId, path, content, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/files?${params.toString()}`, {
        method: 'POST',
        body: JSON.stringify({ path, content })
    });
}

/**
 * 创建文件夹
 */
async function createSessionFolder(userId, sessionId, path, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/folders?${params.toString()}`, {
        method: 'POST',
        body: JSON.stringify({ path })
    });
}

/**
 * 重命名/移动文件或文件夹
 */
async function renameSessionEntry(userId, sessionId, oldPath, newPath, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/rename?${params.toString()}`, {
        method: 'POST',
        body: JSON.stringify({ old_path: oldPath, new_path: newPath })
    });
}

/**
 * 删除文件或文件夹
 */
async function deleteSessionEntry(userId, sessionId, path, recursive = false, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/files?${params.toString()}`, {
        method: 'DELETE',
        body: JSON.stringify({ path, recursive })
    });
}

/**
 * 获取提示词列表
 */
async function getPromptTemplates(scope = 'all', sort = 'recent', q = '') {
    const params = new URLSearchParams({ scope, sort });
    if (q) params.set('q', q);
    return apiRequest(`/prompts?${params.toString()}`, {
        method: 'GET'
    });
}

/**
 * 创建提示词
 */
async function createPromptTemplate(payload) {
    return apiRequest(`/prompts`, {
        method: 'POST',
        body: JSON.stringify(payload)
    });
}

/**
 * 更新提示词
 */
async function updatePromptTemplate(promptId, payload) {
    return apiRequest(`/prompts/${promptId}`, {
        method: 'PUT',
        body: JSON.stringify(payload)
    });
}

/**
 * 删除提示词
 */
async function deletePromptTemplate(promptId) {
    return apiRequest(`/prompts/${promptId}`, {
        method: 'DELETE'
    });
}

/**
 * 记录提示词使用
 */
async function usePromptTemplate(promptId) {
    return apiRequest(`/prompts/${promptId}/use`, {
        method: 'POST'
    });
}

/**
 * 批量删除会话中的所有文件
 */
async function clearAllSessionFiles(userId, sessionId, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/files/all?${params.toString()}`, {
        method: 'DELETE'
    });
}

/**
 * 下载文件，返回临时URL和文件名
 */
async function downloadSessionFile(userId, sessionId, path, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, path, ...(extraParams || {}) });
    const resp = await fetch(`/api/v1/chat/sessions/${sessionId}/download?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include'
    });
    if (!resp.ok) {
        let detail = '下载失败';
        try {
            const data = await resp.json();
            detail = data.detail || detail;
        } catch (e) {
            try {
                detail = await resp.text();
            } catch {}
        }
        throw new Error(`${detail} (HTTP ${resp.status})`);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const filename = path.split('/').filter(Boolean).pop() || 'download';
    const contentType = resp.headers.get('Content-Type') || '';
    return { url, filename, blob, contentType };
}

/**
 * 预览Office文件（服务端转换为PDF）
 */
async function previewSessionFile(userId, sessionId, path, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, path, ...(extraParams || {}) });
    const resp = await fetch(`/api/v1/chat/sessions/${sessionId}/preview?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include'
    });
    if (!resp.ok) {
        let detail = '预览失败';
        try {
            const data = await resp.json();
            detail = data.detail || detail;
        } catch (e) {
            try {
                detail = await resp.text();
            } catch {}
        }
        throw new Error(`${detail} (HTTP ${resp.status})`);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const filename = path.split('/').filter(Boolean).pop() || 'preview.pdf';
    const contentType = resp.headers.get('Content-Type') || '';
    return { url, filename, blob, contentType };
}

/**
 * 获取 Office 预览配置
 */
async function getOfficePreviewSettings() {
    return apiRequest('/onlyoffice/settings');
}

/**
 * 上传文件/文件夹到会话工作目录
 * @param {Array} entries [{ file, path }]
 */
async function uploadSessionFiles(userId, sessionId, entries, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    const formData = new FormData();
    entries.forEach(item => {
        if (!item || !item.file) return;
        const relPath = (item.path || item.file.name || '').replace(/\\/g, '/').replace(/^\/+/, '');
        formData.append('files', item.file, relPath || item.file.name);
    });
    const resp = await fetch(`/api/v1/chat/sessions/${sessionId}/upload?${params.toString()}`, {
        method: 'POST',
        headers: {
            Authorization: getAuthHeaders().Authorization || ''
        },
        body: formData,
        credentials: 'include'
    });
    if (!resp.ok) {
        let detail = '上传失败';
        try {
            const data = await resp.json();
            detail = data.detail || detail;
        } catch (e) {
            try {
                detail = await resp.text();
            } catch {}
        }
        throw new Error(`${detail} (HTTP ${resp.status})`);
    }
    return resp.json();
}

/**
 * 获取归档列表
 */
async function listSessionArchives(userId, sessionId, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/archives?${params.toString()}`);
}

/**
 * 创建归档
 */
async function createSessionArchive(userId, sessionId, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/archives?${params.toString()}`, {
        method: 'POST'
    });
}

/**
 * 恢复归档
 */
async function restoreSessionArchive(userId, sessionId, archiveName, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/archives/${encodeURIComponent(archiveName)}/restore?${params.toString()}`, {
        method: 'POST'
    });
}

/**
 * 清空归档
 */
async function clearSessionArchives(userId, sessionId, extraParams = {}) {
    const params = new URLSearchParams({ user_id: userId, ...(extraParams || {}) });
    return apiRequest(`/chat/sessions/${sessionId}/archives?${params.toString()}`, {
        method: 'DELETE'
    });
}

/**
 * 发布技能
 */
async function publishSkill(formData) {
    const token = getToken();
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    const response = await fetch(`${API_BASE_URL}/skills/publish`, {
        method: 'POST',
        headers,
        body: formData
    });
    const data = await response.json();
    if (!response.ok) {
        if (response.status === 401) {
            clearToken();
            window.location.href = '/login';
            return;
        }
        throw new Error(data.detail || '请求失败');
    }
    return data;
}

/**
 * 获取技能分类列表
 */
async function getSkillCategories() {
    return apiRequest('/skills/categories');
}

/**
 * 获取技能列表
 */
async function getSkillsList(params = {}) {
    const query = new URLSearchParams(params || {});
    const suffix = query.toString() ? `?${query.toString()}` : '';
    return apiRequest(`/skills/list${suffix}`);
}

/**
 * 获取技能详情
 */
async function getSkillDetail(skillId) {
    return apiRequest(`/skills/${skillId}`);
}

/**
 * 获取智能体技能列表（仅 name + content）
 */
async function getAgentSkills(agentId) {
    return apiRequest(`/skills/agent/${agentId}`);
}

/**
 * 安装技能到指定智能体
 */
async function installSkill(skillId, agentId) {
    return apiRequest('/skills/install', {
        method: 'POST',
        body: JSON.stringify({ skill_id: skillId, agent_id: agentId })
    });
}

/**
 * 点赞/点踩技能
 */
async function reactSkill(skillId, action) {
    return apiRequest(`/skills/${skillId}/reaction`, {
        method: 'POST',
        body: JSON.stringify({ action })
    });
}

/**
 * 删除技能
 */
async function deleteSkill(skillId) {
    return apiRequest(`/skills/${skillId}`, {
        method: 'DELETE'
    });
}

/**
 * 编辑技能
 */
async function updateSkill(skillId, formData) {
    const token = getToken();
    const headers = token ? { 'Authorization': `Bearer ${token}` } : {};
    const response = await fetch(`${API_BASE_URL}/skills/${skillId}`, {
        method: 'PUT',
        headers,
        body: formData
    });
    const data = await response.json();
    if (!response.ok) {
        if (response.status === 401) {
            clearToken();
            window.location.href = '/login';
            return;
        }
        throw new Error(data.detail || '请求失败');
    }
    return data;
}

// ==================== MCP API ====================

/**
 * 获取已安装的 MCP 列表
 */
async function getInstalledMCPs() {
    return apiRequest('/mcp/installed');
}

/**
 * 安装 MCP
 * @param {string} url MCP URL
 * @param {string} name MCP 名称
 */
async function installMCP(url, name) {
    return apiRequest('/mcp/install', {
        method: 'POST',
        body: JSON.stringify({ url, name })
    });
}

/**
 * 移除 MCP
 * @param {string} mcpId MCP ID
 */
async function removeMCP(mcpId) {
    return apiRequest(`/mcp/${mcpId}`, {
        method: 'DELETE'
    });
}

/**
 * 获取用户的智能体列表
 */
async function getAgentListByUser(userId) {
    const query = new URLSearchParams({ user_id: userId });
    return apiRequest(`/chat/agent_list?${query.toString()}`);
}

// ==================== 导出所有API方法 ====================

// 创建全局API对象
window.API = {
    // 认证相关
    login,
    logout,
    register,
    getCurrentUser,

    // 好友相关
    getContactsList,
    sendFriendRequest,
    getFriendRequests,
    handleFriendRequest,

    // 智能体相关
    getAgentsList,
    createAiAssistant,
    getAiDefaultPrompt,
    initUserAgents,
    initAgent,
    getAgentStatus,
    startAgentSession,
    endAgentSession,
    sendChatMessage,
    getSessionMessages,
    syncChatMessages,
    getChatSessions,
    getSessionFiles,
    readSessionFile,
    writeSessionFile,
    createSessionFolder,
    renameSessionEntry,
    deleteSessionEntry,
    getPromptTemplates,
    createPromptTemplate,
    updatePromptTemplate,
    deletePromptTemplate,
    usePromptTemplate,
    clearAllSessionFiles,
    downloadSessionFile,
    previewSessionFile,
    getOfficePreviewSettings,
    uploadSessionFiles,
    listSessionArchives,
    createSessionArchive,
    restoreSessionArchive,
    clearSessionArchives,
    publishSkill,
    getSkillCategories,
    getSkillsList,
    getSkillDetail,
    getAgentSkills,
    installSkill,
    getAgentListByUser,
    reactSkill,
    updateSkill,
    deleteSkill,

    // MCP 相关
    getInstalledMCPs,
    installMCP,
    removeMCP,

    // 工具方法
    getToken,
    setToken,
    clearToken,
    getAuthHeaders
};

// 为了向后兼容，也支持模块化导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = window.API;
}
