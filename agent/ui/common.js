// 公共模块
(function() {
    'use strict';

    let membershipChecked = false;

    // 显示"正在开发中"提示
    window.showDevelopingMessage = function() {
        alert('该功能正在开发中，敬请期待！');
    };

    // 统一登出入口（供导航栏和各页面调用）
    window.logout = async function() {
        if (!confirm('确定要退出登录吗？')) {
            return;
        }
        try {
            await fetch('/api/v1/auth/logout', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
                    'Content-Type': 'application/json'
                }
            });
        } catch (error) {
            console.error('登出失败:', error);
        } finally {
            localStorage.removeItem('token');
            localStorage.removeItem('user');
            window.location.href = '/login';
        }
    };

    // 等待导航栏加载完成后再检查会员状态
    function waitForNavbarAndCheck() {
        const navbar = document.querySelector('.navbar');
        if (navbar) {
            // 导航栏已加载，检查会员状态
            checkMembershipAndApplyStyle();
        } else {
            // 导航栏未加载，继续等待
            setTimeout(() => {
                waitForNavbarAndCheck();
            }, 10);
        }
    }

    // 页面加载时自动检查
    document.addEventListener('DOMContentLoaded', function() {
        waitForNavbarAndCheck();
    });

    // 暴露给外部手动调用
    window.checkMembership = checkMembershipAndApplyStyle;

        // 检查会员状态并应用金色样式
    async function checkMembershipAndApplyStyle() {
        if (membershipChecked) return;

        try {
            const token = localStorage.getItem('token');
            if (!token) return;

            const response = await fetch('/api/v1/subscription/membership', {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            });

            membershipChecked = true;

            if (response.ok) {
                const result = await response.json();
                if (result.status === 'success' && result.data) {
                    const navbar = document.querySelector('.navbar');
                    if (navbar) {
                        navbar.classList.add('navbar-member');
                    }
                }
            }
        } catch (error) {
            console.error('检查会员状态失败', error);
        }
    }
})();
