// app.js — 小程序入口
// v3.9+ / 2026-08-24
//
// 职责：
// 1. 检查本地 token，决定初始页（登录页 vs 学习 Tab）
// 2. 暴露全局配置（API_BASE_URL）
// 3. 注册 wx-server 端的 SKILL 路由（开发模式占位）
const STORAGE_TOKEN_KEY = 'ib_access_token';

App({
  globalData: {
    // 后端 API base URL（部署后改成真实域名；本地开发留空 → 用 dev-mock-login）
    apiBaseUrl: 'http://127.0.0.1:8000',
    // 当前用户
    user: null,
    // 调试模式：true 时所有 API 调用打 console.log
    debug: true,
  },

  onLaunch() {
    // 检查本地 token
    const token = wx.getStorageSync(STORAGE_TOKEN_KEY);
    if (token) {
      // 有 token → 后续在 /pages/auth/login 处理过期 / 跳转
      console.log('[app] 已登录，token 存在');
    } else {
      console.log('[app] 未登录');
    }

    // 系统信息
    try {
      const sys = wx.getSystemInfoSync();
      this.globalData.systemInfo = sys;
    } catch (e) {
      console.warn('[app] getSystemInfoSync 失败:', e);
    }
  },

  /** 保存 token 到 storage */
  saveToken(token) {
    wx.setStorageSync(STORAGE_TOKEN_KEY, token);
  },

  /** 清除 token（登出时） */
  clearToken() {
    wx.removeStorageSync(STORAGE_TOKEN_KEY);
  },

  /** 读 token */
  getToken() {
    return wx.getStorageSync(STORAGE_TOKEN_KEY);
  },
});