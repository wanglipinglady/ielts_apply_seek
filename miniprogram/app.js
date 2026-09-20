// app.js — 小程序入口（v3.9+ / 2026-09-20）
const STORAGE_TOKEN_KEY = 'ib_access_token';

App({
  globalData: {
    // 后端 API base URL
    // 真机调试时改成 Mac 局域网 IP（172.20.10.2），模拟器保持 127.0.0.1
    // 临时改法：开发完真机后再改回，或用 getSystemInfo 区分环境
    apiBaseUrl: 'http://172.20.10.2:8000',
    // 当前用户
    user: null,
    // 调试模式：true 时登录页显示"调试登录面板"
    debug: true,
    // 系统信息
    systemInfo: null
  },

  onLaunch() {
    // 检查本地 token
    const token = wx.getStorageSync(STORAGE_TOKEN_KEY);
    if (token) {
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
  }
});