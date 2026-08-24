// pages/me/index/index.ts — 我 Tab（用户中心）
const app = getApp() as any;

Page({
  data: {
    user: null as any,
  },

  onLoad() {
    this.setData({ user: app.globalData.user });
  },

  onShow() {
    this.setData({ user: app.globalData.user });
  },

  goGrade() {
    wx.navigateTo({ url: '/pages/me/grade/index' });
  },
  goExam() {
    wx.navigateTo({ url: '/pages/me/exam/index' });
  },
  goTools() {
    wx.navigateTo({ url: '/pages/me/tools/index' });
  },
  goSettings() {
    wx.showToast({ title: '设置页开发中', icon: 'none' });
  },

  logout() {
    app.clearToken();
    wx.removeStorageSync('ib_refresh_token');
    app.globalData.user = null;
    wx.reLaunch({ url: '/pages/auth/login/index' });
  },
});