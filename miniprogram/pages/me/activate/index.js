// pages/me/activate/index.js — v4.0+：小程序内直接开通 PC 端账号
//
// 业务背景：
// 原来「开通 PC 端账号」只弹窗让用户去 PC 端注册 → 死路。
// 现在小程序内填邮箱 + 密码，后端把占位账号**原地**升级成真实邮箱账号，
// user_id 不变 → 小程序里的学习数据零迁移。
const app = getApp();

function getApiBase() {
  return (app && app.globalData && app.globalData.apiBaseUrl) || 'https://ielts.wanglipingresume.com';
}

Page({
  data: {
    email: '',
    password: '',
    confirmPassword: '',
    submitting: false,
    errorMessage: ''
  },

  onEmailInput(e) {
    this.setData({ email: e.detail.value, errorMessage: '' });
  },

  onPasswordInput(e) {
    this.setData({ password: e.detail.value, errorMessage: '' });
  },

  onConfirmInput(e) {
    this.setData({ confirmPassword: e.detail.value, errorMessage: '' });
  },

  _isValidEmail(email) {
    return /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(email);
  },

  onSubmit() {
    const { email, password, confirmPassword } = this.data;

    if (!this._isValidEmail(email)) {
      this.setData({ errorMessage: '邮箱格式不对' });
      return;
    }
    if (password.length < 8) {
      this.setData({ errorMessage: '密码至少 8 位' });
      return;
    }
    if (password !== confirmPassword) {
      this.setData({ errorMessage: '两次输入的密码不一致' });
      return;
    }

    this.setData({ submitting: true, errorMessage: '' });

    const accessToken = wx.getStorageSync('ib_access_token');
    if (!accessToken) {
      this.setData({ submitting: false, errorMessage: '登录态已失效，请重新登录小程序' });
      setTimeout(() => {
        wx.reLaunch({ url: '/pages/auth/login/index' });
      }, 1500);
      return;
    }

    wx.request({
      url: `${getApiBase()}/api/wx/activate-pc-account`,
      method: 'POST',
      header: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      data: { email, password },
      success: (res) => {
        if (res.statusCode === 200) {
          const { access_token, refresh_token, user } = res.data;
          wx.setStorageSync('ib_access_token', access_token);
          wx.setStorageSync('ib_refresh_token', refresh_token);
          wx.setStorageSync('ib_user', user);

          wx.showModal({
            title: '开通成功',
            content: `现在可以用 ${user.email} 登录 ielts.wanglipingresume.com 了。\n您的学习数据已全部保留。`,
            showCancel: false,
            confirmText: '我知道了',
            success: () => {
              wx.reLaunch({ url: '/pages/me/index/index' });
            }
          });
        } else {
          const errorMap = {
            'EMAIL_TAKEN': '该邮箱已被注册，换一个试试',
            'INVALID_EMAIL': '邮箱格式不对',
            'WEAK_PASSWORD': '密码至少 8 位',
            'ALREADY_ACTIVATED': '该账号已开通 PC 端，请直接重置密码',
            'USER_NOT_FOUND': '账号不存在，请重新登录',
            'INVALID_REQUEST': '当前账号不是微信账号'
          };
          const code = res.data && res.data.code;
          const message = (code && errorMap[code]) || (res.data && res.data.detail) || '开通失败，请稍后重试';
          this.setData({ submitting: false, errorMessage: message });
        }
      },
      fail: (err) => {
        this.setData({ submitting: false, errorMessage: `网络错误: ${err.errMsg}` });
      }
    });
  }
});
