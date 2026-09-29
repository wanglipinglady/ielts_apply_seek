// app.js — 小程序入口（v3.9+ / 2026-09-29 生产配置）
//
// apiBaseUrl 配置说明：
// - 生产：https://ielts.wanglipingresume.com（部署到阿里云 ECS 后）
// - 真机调试：改回 http://172.20.10.2:8001（Mac LAN IP + 雅思助手端口）
// - 模拟器：127.0.0.1:8001
const STORAGE_TOKEN_KEY = 'ib_access_token';

App({
  globalData: {
    // === 生产配置（2026-09-29 部署到阿里云 ECS） ===
    apiBaseUrl: 'https://ielts.wanglipingresume.com',
    // 实际用户
    user: null,
    // 调试模式：true 时登录页显示"调试登录面板"
    // 生产必须改成 false（走真实 wx.login）
    debug: false,
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
