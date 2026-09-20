// pages/review/index/index.js — 复习 Tab 首页（艾宾浩斯核心）v3.9+ / 2026-09-19
const app = getApp();

Page({
  data: {
    activeTab: 'today',
    activeToday: true,
    activeMistakes: false,
    activeTodayClass: 'active',
    activeMistakesClass: '',
    dueWords: [],
    count: 0,
    today: '',
    loading: false,
    band: 0,
    currentIndex: 0,
    isFlipped: false
  },

  onShow() {
    this.loadDueWords();
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab === 'today') {
      this.setData({
        activeTab: 'today',
        activeToday: true,
        activeMistakes: false,
        activeTodayClass: 'active',
        activeMistakesClass: ''
      });
      this.loadDueWords();
    } else if (tab === 'mistakes') {
      this.setData({
        activeTab: 'mistakes',
        activeToday: false,
        activeMistakes: true,
        activeTodayClass: '',
        activeMistakesClass: 'active'
      });
      wx.navigateTo({ url: '/pages/review/mistakes/index' });
    }
  },

  loadDueWords() {
    const app = getApp();
    const that = this;
    this.setData({ loading: true });
    const query = {};
    if (this.data.band > 0) query.band = this.data.band;
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/review/due',
      method: 'GET',
      data: query,
      header: this._authHeader(),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const due_words = body.due_words || body.items || body.words || [];
          that.setData({
            dueWords: due_words,
            count: body.count || due_words.length,
            today: body.today || '',
            currentIndex: 0,
            isFlipped: false
          });
        }
      },
      fail: () => {},
      complete: () => that.setData({ loading: false })
    });
  },

  flipCard() {
    this.setData({ isFlipped: !this.data.isFlipped });
  },

  onKnow() {
    this.submitReview(true);
  },

  onDontKnow() {
    this.submitReview(false);
  },

  submitReview(correct) {
    const word = this.data.dueWords[this.data.currentIndex];
    if (!word) return;
    const app = getApp();
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/review/submit',
      method: 'POST',
      data: { word: word.word, correct: correct },
      header: Object.assign({ 'Content-Type': 'application/json' }, this._authHeader()),
      success: () => {},
      fail: () => {}
    });
    this.setData({
      currentIndex: this.data.currentIndex + 1,
      isFlipped: false
    });
  },

  _authHeader() {
    const token = wx.getStorageSync('ib_access_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }
});