// pages/me/index/index.js — 个人中心页（v3.9+ / 2026-09-19）
const app = getApp();

Page({
  data: {
    user: null,
    avatarSrc: '/assets/avatar-default.png',
    displayName: '微信用户',
    displayEmail: '未绑定邮箱'
  },

  onShow() {
    const user = wx.getStorageSync('ib_user');
    if (user) {
      this.setData({
        user: user,
        avatarSrc: user.avatar_url || '/assets/avatar-default.png',
        displayName: user.nickname || '微信用户',
        displayEmail: user.email || '未绑定邮箱'
      });
    }
  },

  goGrade() {
    // 保留代码但已不在 UI 使用（功能已从"我"页面移除）
    wx.navigateTo({ url: '/pages/me/grade/index' });
  },

  goExam() {
    // 用 navigateTo 不用 switchTab：exam 页不是 tabBar 页
    wx.navigateTo({ url: '/pages/me/exam/index' });
  },

  goTools() {
    // 保留代码但已不在 UI 使用（功能已从"我"页面移除）
    wx.navigateTo({ url: '/pages/me/tools/index' });
  },

  doLogout() {
    wx.showModal({
      title: '退出登录',
      content: '确认退出当前账号？',
      success: function(res) {
        if (res.confirm) {
          wx.removeStorageSync('ib_access_token');
          wx.removeStorageSync('ib_refresh_token');
          wx.removeStorageSync('ib_user');
          wx.reLaunch({ url: '/pages/auth/login/index' });
        }
      }
    });
  }
});