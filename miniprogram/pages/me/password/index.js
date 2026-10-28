// pages/me/password/index.js — v4.0+：重置 PC 端登录密码
//
// 业务背景：
// 账号在 PC 端登录过（pc_logged_in_at 有值）后邮箱被锁定不能改，
// 但用户可能忘了密码 → 只能重置密码。
// 安全模型：登录态（微信身份）+ 邮箱必须等于当前账号邮箱 → 不能改别人的密码。
const app = getApp();

function getApiBase() {
  return (app && app.globalData && app.globalData.apiBaseUrl) || 'https://ielts.wanglipingresume.com';
}

Page({
  data: {
    email: '',
    newPassword: '',
    confirmPassword: '',
    submitting: false,
    errorMessage: ''
  },

  onLoad() {
    // 默认带出当前账号邮箱（用户一般不需要改）
    const user = wx.getStorageSync('ib_user');
    if (user && user.email) {
      this.setData({ email: user.email });
    }
  },

  onEmailInput(e) {
    this.setData({ email: e.detail.value, errorMessage: '' });
  },

  onPasswordInput(e) {
    this.setData({ newPassword: e.detail.value, errorMessage: '' });
  },

  onConfirmInput(e) {
    this.setData({ confirmPassword: e.detail.value, errorMessage: '' });
  },

  onSubmit() {
    const { email, newPassword, confirmPassword } = this.data;

    if (!email) {
      this.setData({ errorMessage: '请填写邮箱' });
      return;
    }
    if (newPassword.length < 8) {
      this.setData({ errorMessage: '新密码至少 8 位' });
      return;
    }
    if (newPassword !== confirmPassword) {
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
      url: `${getApiBase()}/api/wx/reset-password`,
      method: 'POST',
      header: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      data: { email, new_password: newPassword },
      success: (res) => {
        if (res.statusCode === 200) {
          wx.showModal({
            title: '重置成功',
            content: '新密码已生效，请用新密码登录 ielts.wanglipingresume.com。',
            showCancel: false,
            confirmText: '我知道了',
            success: () => {
              wx.reLaunch({ url: '/pages/me/index/index' });
            }
          });
        } else {
          const errorMap = {
            'EMAIL_MISMATCH': '邮箱与当前账号不一致',
            'WEAK_PASSWORD': '新密码至少 8 位',
            'USER_NOT_FOUND': '账号不存在，请重新登录',
            'INVALID_EMAIL': '邮箱格式不对'
          };
          const code = res.data && res.data.code;
          const message = (code && errorMap[code]) || (res.data && res.data.detail) || '重置失败，请稍后重试';
          this.setData({ submitting: false, errorMessage: message });
        }
      },
      fail: (err) => {
        this.setData({ submitting: false, errorMessage: `网络错误: ${err.errMsg}` });
      }
    });
  }
});
