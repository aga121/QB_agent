// 权限检查通用模块
(function() {
    'use strict';

    // 显示无权限访问页面
    function showNoAccessPage() {
        document.body.innerHTML = `
            <div style="display: flex; justify-content: center; align-items: center; height: 100vh; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;">
                <div style="background: white; padding: 40px; border-radius: 20px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.2);">
                    <i class="fas fa-exclamation-triangle" style="font-size: 64px; color: #ffc107; margin-bottom: 20px;"></i>
                    <h2 style="color: #333; margin-bottom: 15px;">您无权限访问</h2>
                    <p style="color: #666; margin-bottom: 30px;">请先登录后使用系统</p>
                    <button onclick="goToLogin()" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 12px 30px; border-radius: 25px; font-size: 16px; cursor: pointer; transition: transform 0.3s;">
                        返回登录
                    </button>
                </div>
            </div>
        `;
    }

    // 检查用户是否已登录
    window.checkAuth = function() {
        const token = localStorage.getItem('token');
        const user = localStorage.getItem('user');

        if (!token || !user) {
            showNoAccessPage();
            return false;
        }

        // 这里可以添加token验证（可选）
        // 由于是简单实现，我们主要检查token是否存在
        // 实际生产环境应该验证token的有效性

        return true;
    };

    // 返回登录页面
    window.goToLogin = function() {
        localStorage.clear(); // 清除所有本地存储
        window.location.href = '/';
    };

    // 获取当前用户信息
    window.getCurrentUser = function() {
        const userStr = localStorage.getItem('user');
        return userStr ? JSON.parse(userStr) : null;
    };

    // 初始化用户信息显示
    window.initUserInfo = function() {
        const user = window.getCurrentUser();
        if (!user) return;

        const userName = user.username || '用户';
        const firstLetter = userName !== '用户' ? userName.charAt(0).toUpperCase() : 'U';

        // 更新导航栏的用户信息
        const navUserAvatar = document.getElementById('navUserAvatar');
        const navUserNameEl = document.getElementById('navUserName');

        if (navUserNameEl) {
            navUserNameEl.textContent = userName;
        }

        if (navUserAvatar) {
            navUserAvatar.textContent = firstLetter;
        }
    };

    // 自动检查权限（如果页面有 data-require-auth 属性）
    document.addEventListener('DOMContentLoaded', function() {
        if (document.body.hasAttribute('data-require-auth')) {
            if (!window.checkAuth()) {
                return;
            }
            window.initUserInfo();
        }
    });
})();