// pages/study/random/index.js — 随机刷词（艾宾浩斯学习模式）v3.9+ / 2026-09-20
//
// 与 Web 端「随机学习」完全对齐：
//   1. 抽 N 个 Band X 词（vocab/random，不写学习记录）
//   2. 卡片翻转：默认显示英文 → 点"显示答案"或点卡片 → 显示音标+释义
//   3. 用户判断：点"认识 ✓" → is_correct=true；点"不认识 ✗" → is_correct=false
//   4. 调 /api/wx/study/review/submit 写入 learning_records（艾宾浩斯算法在 service 层）
//   5. 自动下一题，全部完成后显示统计

const app = getApp();

Page({
  data: {
    band: 7,
    count: 10,
    counts: [5, 10, 15, 20],
    countsIndex: 1,
    words: [],
    currentIndex: 0,
    isFlipped: false,
    knownCount: 0,
    unknownCount: 0,
    progressPercent: 0,
    finished: false,
    loading: false
  },

  onLoad(options) {
    if (options && options.band) {
      this.setData({ band: parseInt(options.band) || 7 });
    }
    // 不自动抽词，让用户点按钮开始
  },

  onBandChange(e) {
    this.setData({ band: parseInt(e.detail.value) + 5 });
    this.restart();
  },

  onCountChange(e) {
    const idx = parseInt(e.detail.value);
    this.setData({ count: this.data.counts[idx], countsIndex: idx });
    this.restart();
  },

  loadRandom() {
    const app = getApp();
    this.setData({ loading: true });
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/vocab/random',
      method: 'POST',
      data: { band: this.data.band, count: this.data.count },
      header: Object.assign({ 'Content-Type': 'application/json' }, this._authHeader()),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const words = body.words || body.items || [];
          words.forEach((w) => {
            if (!w.pos) w.pos = 'n.';
          });
          this.setData({
            words: words,
            currentIndex: 0,
            isFlipped: false,
            knownCount: 0,
            unknownCount: 0,
            progressPercent: words.length > 0 ? Math.round(1 * 100 / words.length) : 0,
            finished: false
          });
        } else {
          wx.showToast({ title: '抽词失败 ' + res.statusCode, icon: 'none' });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ loading: false })
    });
  },

  // 翻转卡片（点击卡片本体或"显示答案"按钮）
  flipCard() {
    if (this.data.isFlipped) return;  // 已显示答案，不重复
    this.setData({ isFlipped: true });
  },

  // "认识"按钮 → 调 review/submit(is_correct=true) → 下一题
  onKnown() {
    this._submitAnswer(true);
  },

  // "不认识"按钮 → 调 review/submit(is_correct=false) → 下一题
  onUnknown() {
    this._submitAnswer(false);
  },

  // 提交评分到后端（写艾宾浩斯学习记录）+ 切下一题
  _submitAnswer(isCorrect) {
    const { words, currentIndex, knownCount, unknownCount } = this.data;
    if (!words[currentIndex]) return;
    const word = words[currentIndex];

    // 调后端写入 learning_records（艾宾浩斯算法在 service 层）
    const app = getApp();
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/review/submit',
      method: 'POST',
      data: {
        word: word.word,
        correct: isCorrect
      },
      header: Object.assign({ 'Content-Type': 'application/json' }, this._authHeader()),
      success: (res) => {
        // 写库成功，UI 切下一题
        if (!isCorrect) {
          wx.showToast({ title: '已加入错题本', icon: 'none', duration: 1200 });
        }
      },
      fail: () => {
        wx.showToast({ title: '记录失败，请重试', icon: 'none' });
      }
    });

    // 立即切下一题（不阻塞 UI）
    const newKnown = knownCount + (isCorrect ? 1 : 0);
    const newUnknown = unknownCount + (isCorrect ? 0 : 1);
    const nextIdx = currentIndex + 1;

    if (nextIdx >= words.length) {
      this.setData({
        finished: true,
        knownCount: newKnown,
        unknownCount: newUnknown,
        progressPercent: 100,
        isFlipped: false
      });
      wx.showToast({ title: '本轮完成！', icon: 'success' });
    } else {
      this.setData({
        currentIndex: nextIdx,
        knownCount: newKnown,
        unknownCount: newUnknown,
        isFlipped: false,
        progressPercent: Math.round((nextIdx + 1) * 100 / words.length)
      });
    }
  },

  restart() {
    this.loadRandom();
  },

  _authHeader() {
    const token = wx.getStorageSync('ib_access_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }
});