// pages/me/merge/index.js — v4.0+：合并 PC 端账号页面
const app = getApp();

// v4.0+：API_BASE 统一从 globalData 读，dev/prod 自动切
// 本地测试：app.js globalData.apiBaseUrl = 'https://ielts.wanglipingresume.com'
// 生产：app.js globalData.apiBaseUrl = 'https://ielts.wanglipingresume.com'
function getApiBase() {
  return (app && app.globalData && app.globalData.apiBaseUrl) || 'https://ielts.wanglipingresume.com';
}

Page({
  data: {
    email: '',
    password: '',
    submitting: false,
    errorMessage: ''
  },

  onEmailInput(e) {
    this.setData({ email: e.detail.value, errorMessage: '' });
  },

  onPasswordInput(e) {
    this.setData({ password: e.detail.value, errorMessage: '' });
  },

  _isValidEmail(email) {
    return /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(email);
  },

  onSubmit() {
    const { email, password } = this.data;

    if (!this._isValidEmail(email)) {
      this.setData({ errorMessage: '邮箱格式不对' });
      return;
    }
    if (password.length < 8) {
      this.setData({ errorMessage: '密码至少 8 位' });
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
      url: `${getApiBase()}/api/wx/merge-to-existing`,
      method: 'POST',
      header: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      data: { email, password },
      success: (res) => {
        if (res.statusCode === 200) {
          const { access_token, refresh_token, user, merged_vocab_count } = res.data;
          wx.setStorageSync('ib_access_token', access_token);
          wx.setStorageSync('ib_refresh_token', refresh_token);
          wx.setStorageSync('ib_user', user);

          wx.showModal({
            title: '合并成功',
            content: `已合并 ${merged_vocab_count} 个学习记录。\n现在您以 ${user.email} 身份登录。`,
            showCancel: false,
            confirmText: '我知道了',
            success: () => {
              wx.reLaunch({ url: '/pages/me/index/index' });
            }
          });
        } else {
          const errorMap = {
            'USER_NOT_FOUND': '该邮箱未注册',
            'INVALID_CREDENTIALS': '邮箱或密码错误',
            'INVALID_TARGET': '该账号是占位账号，不能作为合并目标',
            'ALREADY_BOUND': '该邮箱已绑定其他微信，请先在 PC 端解绑',
            'CANNOT_MERGE_SELF': '合并目标不能是当前账号',
            'MERGE_FAILED': '合并失败（已自动回滚）',
            'INVALID_REQUEST': '当前账号不是微信账号',
            'INVALID_OPENID': 'openid 无效'
          };
          const code = res.data && res.data.code;
          const message = (code && errorMap[code]) || (res.data && res.data.detail) || '合并失败，请稍后重试';
          this.setData({ submitting: false, errorMessage: message });
        }
      },
      fail: (err) => {
        this.setData({ submitting: false, errorMessage: `网络错误: ${err.errMsg}` });
      }
    });
  },

  onCancel() {
    wx.navigateBack();
  }
});
