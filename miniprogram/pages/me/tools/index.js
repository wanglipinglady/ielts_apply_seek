// pages/me/tools/index.js — 工具集合 v3.9+ / 2026-09-20
// 工具：番茄钟 / 文章翻译 / 备考资源 / 词汇测验 / 错词本
// 实现：本地工具（不需要后端）+ 部分跳转

const app = getApp();

Page({
  data: {
    pomodoroTime: '25:00',
    pomodoroRunning: false,
    pomodoroSeconds: 25 * 60,
    pomodoroTimer: null,
    pomodoroSessions: 0,
    translateInput: '',
    translateResult: null,
    translateLoading: false,
    translateButtonText: '开始翻译'
  },

  onUnload() {
    this._stopPomodoro();
  },

  // ============ 番茄钟 ============
  startPomodoro() {
    if (this.data.pomodoroRunning) return;
    const that = this;
    const timer = setInterval(() => {
      let secs = that.data.pomodoroSeconds - 1;
      if (secs <= 0) {
        // 完成一个番茄钟
        clearInterval(that.data.pomodoroTimer);
        that.setData({
          pomodoroRunning: false,
          pomodoroSeconds: 25 * 60,
          pomodoroTime: '25:00',
          pomodoroTimer: null,
          pomodoroSessions: that.data.pomodoroSessions + 1
        });
        wx.showToast({ title: '🎉 完成 1 个番茄钟！', icon: 'success' });
        wx.vibrateShort && wx.vibrateShort({ type: 'medium' });
        return;
      }
      const mm = String(Math.floor(secs / 60)).padStart(2, '0');
      const ss = String(secs % 60).padStart(2, '0');
      that.setData({
        pomodoroSeconds: secs,
        pomodoroTime: mm + ':' + ss
      });
    }, 1000);
    this.setData({
      pomodoroRunning: true,
      pomodoroTimer: timer
    });
  },

  pausePomodoro() {
    this._stopPomodoro();
    this.setData({ pomodoroRunning: false });
  },

  resetPomodoro() {
    this._stopPomodoro();
    this.setData({
      pomodoroRunning: false,
      pomodoroSeconds: 25 * 60,
      pomodoroTime: '25:00'
    });
  },

  _stopPomodoro() {
    if (this.data.pomodoroTimer) {
      clearInterval(this.data.pomodoroTimer);
      this.setData({ pomodoroTimer: null });
    }
  },

  // ============ 文章翻译 ============
  onTranslateInput(e) {
    this.setData({ translateInput: e.detail.value });
  },

  async onTranslate() {
    if (!this.data.translateInput.trim() || this.data.translateInput.length < 20) {
      wx.showToast({ title: '请输入至少 20 字符', icon: 'none' });
      return;
    }
    const app = getApp();
    const token = wx.getStorageSync('ib_access_token');
    this.setData({ translateLoading: true, translateButtonText: '翻译中...' });
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/articles/translate',
      method: 'POST',
      data: { source_text: this.data.translateInput, extract_words: true },
      header: token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          this.setData({ translateResult: res.data });
          wx.showToast({ title: '翻译完成', icon: 'success' });
        } else {
          let msg = '翻译失败 ' + res.statusCode;
          if (res.data && res.data.detail) {
            msg = typeof res.data.detail === 'string' ? res.data.detail : JSON.stringify(res.data.detail);
          }
          wx.showToast({ title: msg, icon: 'none' });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ translateLoading: false, translateButtonText: '开始翻译' })
    });
  },

  // ============ 工具入口跳转（用 navigateTo，因为只有 study/review/speak/me 是 tabBar 页） ============
  onTapTool(e) {
    const tool = e.currentTarget.dataset.tool;
    if (tool === 'mistakes') {
      wx.navigateTo({ url: '/pages/review/mistakes/index' });
    } else if (tool === 'speak') {
      wx.navigateTo({ url: '/pages/speak/index/index' });
    } else if (tool === 'grade') {
      wx.navigateTo({ url: '/pages/me/grade/index' });
    } else if (tool === 'exam') {
      wx.navigateTo({ url: '/pages/me/exam/index' });
    } else if (tool === 'random') {
      wx.navigateTo({ url: '/pages/study/random/index' });
    } else if (tool === 'quiz') {
      wx.navigateTo({ url: '/pages/study/quiz/index' });
    } else {
      wx.showToast({ title: '开发中', icon: 'none' });
    }
  }
});