// pages/auth/login/index.js — 登录页（v3.9+ / 2026-09-19）
const app = getApp();

Page({
  data: {
    nickname: '',
    loading: false,
    errorMsg: '',
    isDev: false,
    showDevPanel: true,
    devCode: 'test_user001',
    loginButtonText: '微信一键登录',
    devPanelToggleText: '收起 调试登录面板'
  },

  onLoad() {
    const debug = app.globalData.debug;
    this.setData({ isDev: !!debug });
  },

  onNicknameInput(e) {
    this.setData({ nickname: e.detail.value });
  },

  doLogin() {
    if (this.data.loading) return;
    this.setData({ loading: true, errorMsg: '', loginButtonText: '登录中...' });

    // IDE 调试模式：直接走 dev-mock-login（绕过 wx.login 真实调用）
    if (app.globalData.debug) {
      // 用固定的 mockCode（不用 Date.now），保证同用户复用错题本/学习记录
      const mockCode = 'dev_test_user001';
      this._doLoginRequest('/api/wx/dev-mock-login', mockCode);
      return;
    }

    // 正式环境：调真实 wx.login
    wx.login({
      success: (loginRes) => {
        if (!loginRes.code) {
          this.setData({ loading: false, errorMsg: 'wx.login 未返回 code', loginButtonText: '微信一键登录' });
          return;
        }
        this._doLoginRequest('/api/wx/login', loginRes.code);
      },
      fail: () => {
        this.setData({ loading: false, errorMsg: 'wx.login 调用失败', loginButtonText: '微信一键登录' });
      }
    });
  },

  _doLoginRequest(url, code) {
    wx.request({
      url: app.globalData.apiBaseUrl + url,
      method: 'POST',
      data: { code: code, nickname: this.data.nickname || undefined },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          this._afterLogin(res.data);
        } else {
          let errMsg = '登录失败 ' + res.statusCode;
          if (res.data && res.data.detail) {
            if (typeof res.data.detail === 'string') {
              errMsg = res.data.detail;
            } else if (Array.isArray(res.data.detail)) {
              errMsg = res.data.detail.map(d => d.msg || JSON.stringify(d)).join('; ');
            }
          }
          this.setData({ loading: false, errorMsg: errMsg, loginButtonText: '微信一键登录' });
        }
      },
      fail: () => {
        this.setData({ loading: false, errorMsg: '网络异常（请确认后端已启动并设置"不校验合法域名"）', loginButtonText: '微信一键登录' });
      }
    });
  },

  toggleDevPanel() {
    const newState = !this.data.showDevPanel;
    this.setData({
      showDevPanel: newState,
      devPanelToggleText: newState ? '收起 调试登录面板' : '展开 调试登录面板'
    });
  },

  onDevCodeInput(e) {
    this.setData({ devCode: e.detail.value });
  },

  doDevLogin() {
    if (this.data.loading) return;
    const code = (this.data.devCode || '').trim();
    if (!code) {
      this.setData({ errorMsg: '请输入调试 code' });
      return;
    }
    this.setData({ loading: true, errorMsg: '' });
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/dev-mock-login',
      method: 'POST',
      data: { code: code, nickname: this.data.nickname || undefined },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          this._afterLogin(res.data);
        } else {
          this.setData({ loading: false, errorMsg: '登录失败 ' + res.statusCode, loginButtonText: '微信一键登录' });
        }
      },
      fail: () => {
        this.setData({ loading: false, errorMsg: '网络异常', loginButtonText: '微信一键登录' });
      }
    });
  },

  _afterLogin(data) {
    app.saveToken(data.access_token);
    wx.setStorageSync('ib_refresh_token', data.refresh_token);
    wx.setStorageSync('ib_user', data.user);
    wx.showToast({
      title: data.is_new_user ? '注册成功 🎉' : '欢迎回来',
      icon: 'success'
    });
    setTimeout(() => {
      wx.switchTab({ url: '/pages/study/index/index' });
    }, 600);
    this.setData({ loading: false, loginButtonText: '微信一键登录' });
  }
});