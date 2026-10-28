// pages/me/index/index.js — 个人中心页（v3.9+ / 2026-09-19，v4.0+ 加 PC 端账号区域）
const app = getApp();

Page({
  data: {
    user: null,
    avatarSrc: '/assets/avatar-default.png',
    displayName: '微信用户',
    displayEmail: '未绑定邮箱',
    // v4.0+：PC 端账号区域状态
    // - 'placeholder'：占位账号（@wechat.ielts-buddy.local），未开通
    // - 'bound'：已开通，但还没用 PC 端登录过（可编辑）
    // - 'locked'：已用 PC 端登录过（邮箱锁定，仅密码可重置）
    pcAccountState: 'placeholder'
  },

  onShow() {
    const user = wx.getStorageSync('ib_user');
    if (user) {
      // v4.0+：计算 pcAccountState
      const isPlaceholder = !!(user.email && user.email.endsWith('@wechat.ielts-buddy.local'));
      let pcAccountState = 'placeholder';
      if (!isPlaceholder) {
        // 是真邮箱 → 已开通
        pcAccountState = user.pc_logged_in_at ? 'locked' : 'bound';
      }

      // v4.0+ 调试：apiMode = 'local' | 'prod'
      const apiBase = (app.globalData && app.globalData.apiBaseUrl) || '';
      const apiMode = apiBase.includes('127.0.0.1') || apiBase.includes('localhost') ? 'local' : 'prod';

      this.setData({
        user: user,
        avatarSrc: user.avatar_url || '/assets/avatar-default.png',
        displayName: user.nickname || '微信用户',
        displayEmail: user.email || '未绑定邮箱',
        pcAccountState: pcAccountState,
        debug: !!(app.globalData && app.globalData.debug),
        apiMode: apiMode
      });
    }
  },

  // v4.0+：占位账号用户点"开通 PC 端"
  onOpenPCAccount() {
    const user = this.data.user;
    if (!user) return;

    // 弹窗让用户选择：直接开通 OR 合并已有 PC 端账号
    wx.showActionSheet({
      itemList: ['开通新 PC 端账号（填邮箱+密码）', '合并已有 PC 端账号（输 PC 端邮箱+密码）'],
      success: (res) => {
        if (res.tapIndex === 0) {
          // 选项 1：小程序内直接开通（不再跳去 PC 端注册）
          wx.navigateTo({ url: '/pages/me/activate/index' });
        } else if (res.tapIndex === 1) {
          // 选项 2：合并已有 PC 端账号 → 跳转到合并页
          wx.navigateTo({ url: '/pages/me/merge/index' });
        }
      }
    });
  },

  // v4.0+：重置 PC 端登录密码（邮箱锁定后仍可重置密码）
  onChangePassword() {
    wx.navigateTo({ url: '/pages/me/password/index' });
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