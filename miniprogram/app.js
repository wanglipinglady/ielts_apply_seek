// app.js — 小程序入口（v3.9+ / 2026-09-29 生产配置，v4.0+ 本地测试模式）
//
// ===== 环境切换（只改这一个常量）=====
// 'local'    本地后端 https://ielts.wanglipingresume.com（微信开发者工具模拟器）
// 'lan'      本地后端 http://<Mac局域网IP>:8001（真机调试，需改 LAN_HOST）
// 'prod'     生产 https://ielts.wanglipingresume.com
//
// v4.0+ 调试要点：
// - local/lan 模式：debug=true，登录页显示"调试登录面板"，可走 dev-mock-login
// - prod 模式：debug=false，走真实 wx.login
const ENV = 'prod';

// 真机调试时填你 Mac 的局域网 IP（终端执行 `ipconfig getifaddr en0` 获取）
const LAN_HOST = '192.168.1.100';

const ENV_CONFIG = {
  local: { apiBaseUrl: 'https://ielts.wanglipingresume.com', debug: true },
  lan:   { apiBaseUrl: `http://${LAN_HOST}:8001`, debug: true },
  prod:  { apiBaseUrl: 'https://ielts.wanglipingresume.com', debug: false },
};

const STORAGE_TOKEN_KEY = 'ib_access_token';

App({
  globalData: {
    // 当前环境（供页面判断）
    env: ENV,
    apiBaseUrl: ENV_CONFIG[ENV].apiBaseUrl,
    user: null,
    // 调试模式：true 时登录页显示"调试登录面板"
    debug: ENV_CONFIG[ENV].debug,
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
