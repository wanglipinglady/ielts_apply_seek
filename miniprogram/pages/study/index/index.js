// pages/study/index/index.js — 学习 Tab 首页（v3.9+ / 2026-09-20 内联 random 学习）
const app = getApp();

Page({
  data: {
    user: null,
    activeTab: 'browse',
    activeBrowse: true,
    activeRandom: false,
    activeQuiz: false,
    activeBrowseClass: 'active',
    activeRandomClass: '',
    activeQuizClass: '',
    band: 7,
    bandIndex: 2,
    streakDays: 0,
    learnedCount: 0,
    dueToday: 0,
    words: [],
    loading: false,
    // === 内联 random 学习状态（替代独立 random 页，避免 navigateTo 不可靠） ===
    randomWords: [],
    randomCurrentIndex: 0,
    randomFlipped: false,
    randomKnown: 0,
    randomUnknown: 0,
    randomProgress: 0,
    randomFinished: false,
    randomLoading: false,
    // 数量选项：4 个数字直接展开为 view（不用 wx:for, picker, 按钮 - 之前的方案都有兼容问题）
    randomCounts: [5, 10, 15, 20],
    randomCountIndex: 1,
    randomCount: 10,
    countCls0: '',
    countCls1: 'count-opt-active',
    countCls2: '',
    countCls3: ''
  },

  onShow() {
    const user = wx.getStorageSync('ib_user');
    if (user) {
      const stats = user.stats || {};
      this.setData({
        user: user,
        streakDays: stats.streak_days || 0,
        learnedCount: stats.learned_count || 0,
        dueToday: stats.due_today || 0
      });
    }
    if (this.data.words.length === 0 && this.data.activeTab === 'browse') {
      this.loadBrowse();
    }
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({
      activeTab: tab,
      activeBrowse: tab === 'browse',
      activeRandom: tab === 'random',
      activeQuiz: tab === 'quiz',
      activeBrowseClass: tab === 'browse' ? 'active' : '',
      activeRandomClass: tab === 'random' ? 'active' : '',
      activeQuizClass: tab === 'quiz' ? 'active' : '',
      words: []
    });
    if (tab === 'browse') this.loadBrowse();
  },

  onBandChange(e) {
    const bandIndex = parseInt(e.detail.value);
    const band = bandIndex + 5;
    this.setData({ band: band, bandIndex: bandIndex });
    if (this.data.activeTab === 'browse') this.loadBrowse();
  },

  loadBrowse() {
    const app = getApp();
    this.setData({ loading: true });
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/vocab/list',
      method: 'GET',
      data: { band: this.data.band, count: 20 },
      header: this._authHeader(),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const items = body.items || body.words || body.vocab || [];
          this.setData({ words: items });
        } else {
          wx.showToast({ title: '加载失败', icon: 'none' });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ loading: false })
    });
  },

  // ===== 内联 random 学习（替代独立 random 页） =====

  onLoad() {
    // 诊断：打印当前 Page 实例的所有方法名（IDE 应该能看到 onPick5/10/15/20）
    console.log('[study/index onLoad] Page methods:', Object.keys(this).filter(k => typeof this[k] === 'function').join(','));
  },

  onRandomCountChange(e) {
    const idx = parseInt(e.detail.value);
    this._setRandomCount(idx);
  },

  // 数量选择：用 4 个独立方法（不用 onPickCount + data-idx）避免 IDE 第二次点击吞事件
  onPick5() { console.log('[onPick5] clicked'); this._setRandomCount(0); },
  onPick10() { console.log('[onPick10] clicked'); this._setRandomCount(1); },
  onPick15() { console.log('[onPick15] clicked'); this._setRandomCount(2); },
  onPick20() { console.log('[onPick20] clicked'); this._setRandomCount(3); },

  _setRandomCount(idx) {
    // 同时更新当前选中数量 + 4 个 view 的 active class（wxml 不用三元）
    const update = {
      randomCountIndex: idx,
      randomCount: this.data.randomCounts[idx]
    };
    update.countCls0 = idx === 0 ? 'count-opt-active' : '';
    update.countCls1 = idx === 1 ? 'count-opt-active' : '';
    update.countCls2 = idx === 2 ? 'count-opt-active' : '';
    update.countCls3 = idx === 3 ? 'count-opt-active' : '';
    this.setData(update);
  },

  onStartRandom() {
    this.setData({ randomLoading: true });
    const app = getApp();
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/vocab/random',
      method: 'POST',
      data: { band: this.data.band, count: this.data.randomCount },
      header: Object.assign({ 'Content-Type': 'application/json' }, this._authHeader()),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const words = body.words || body.items || [];
          words.forEach((w) => { if (!w.pos) w.pos = 'n.'; });
          this.setData({
            randomWords: words,
            randomCurrentIndex: 0,
            randomFlipped: false,
            randomKnown: 0,
            randomUnknown: 0,
            randomProgress: words.length > 0 ? Math.round(1 * 100 / words.length) : 0,
            randomFinished: false
          });
        } else {
          wx.showToast({ title: '抽词失败 ' + res.statusCode, icon: 'none' });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ randomLoading: false })
    });
  },

  onFlipRandom() {
    if (this.data.randomFlipped) return;
    this.setData({ randomFlipped: true });
  },

  onRandomKnown() { this._submitRandomAnswer(true); },
  onRandomUnknown() { this._submitRandomAnswer(false); },

  _submitRandomAnswer(isCorrect) {
    const { randomWords, randomCurrentIndex, randomKnown, randomUnknown } = this.data;
    const word = randomWords[randomCurrentIndex];
    if (!word) return;
    const app = getApp();
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/review/submit',
      method: 'POST',
      data: { word: word.word, correct: isCorrect },
      header: Object.assign({ 'Content-Type': 'application/json' }, this._authHeader()),
      success: () => {
        if (!isCorrect) wx.showToast({ title: '已加入错词本', icon: 'none', duration: 1000 });
      },
      fail: () => wx.showToast({ title: '记录失败', icon: 'none' })
    });
    const newKnown = randomKnown + (isCorrect ? 1 : 0);
    const newUnknown = randomUnknown + (isCorrect ? 0 : 1);
    const nextIdx = randomCurrentIndex + 1;
    if (nextIdx >= randomWords.length) {
      this.setData({
        randomFinished: true,
        randomKnown: newKnown,
        randomUnknown: newUnknown,
        randomProgress: 100,
        randomFlipped: false
      });
      wx.showToast({ title: '本轮完成！', icon: 'success' });
    } else {
      this.setData({
        randomCurrentIndex: nextIdx,
        randomKnown: newKnown,
        randomUnknown: newUnknown,
        randomFlipped: false,
        randomProgress: Math.round((nextIdx + 1) * 100 / randomWords.length)
      });
    }
  },

  // ===== /内联 random 学习 =====

  onRandomTap() {
    // 兼容旧入口：现在已不再跳转独立 random 页，保留方法防 IDE 缓存误调用
    // （主入口改为直接在 random tab 内联操作）
    wx.showToast({ title: '请使用下方"开始随机学习"', icon: 'none' });
  },

  goQuiz() {
    // 用 navigateTo 不用 reLaunch：保留返回栈，让 quiz 页有"返回"按钮
    wx.navigateTo({ url: '/pages/study/quiz/index?band=' + this.data.band });
  },

  _authHeader() {
    const token = wx.getStorageSync('ib_access_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }
});