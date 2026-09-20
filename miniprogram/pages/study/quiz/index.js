// pages/study/quiz/index.js — 单词背诵（艾宾浩斯复习）v3.9+ / 2026-09-19
const app = getApp();

Page({
  data: {
    mode: 'en2zh',
    modeRange: ['en2zh', 'zh2en'],
    modeIndex: 0,
    modeLabel: '英译中',
    placeholder: '输入中文释义',
    band: 7,
    questions: [],
    currentIndex: 0,
    userAnswer: '',
    finished: false,
    correctCount: 0,
    progressPercent: 0,
    loading: false,
    showResult: false,
    isCorrect: false,
    correctAnswer: '',
    resultIcon: '✅',
    resultTitle: '答对了！',
    resultTitleClass: 'result-correct'
  },

  onLoad(options) {
    console.log('[quiz onLoad] options=', options);
    if (options && options.band) {
      this.setData({ band: parseInt(options.band) || 7 });
    }
    console.log('[quiz onLoad] calling loadDueWords, band=', this.data.band);
    this.loadDueWords();
  },

  onModeChange(e) {
    // bindtap 触发（替代 picker）：循环切换英译中 ↔ 中译英
    console.log('[onModeChange] current mode=', this.data.mode);
    const next = this.data.mode === 'en2zh' ? 1 : 0;
    const mode = next === 0 ? 'en2zh' : 'zh2en';
    console.log('[onModeChange] next mode=', mode);
    this.setData({
      mode: mode,
      modeIndex: next,
      modeLabel: mode === 'en2zh' ? '英译中' : '中译英',
      placeholder: mode === 'en2zh' ? '输入中文释义' : '输入英文单词'
    });
  },

  onBandChange(e) {
    // bindtap 触发（替代 picker）：循环切换 band 5→6→7→8→9→5
    console.log('[onBandChange] current band=', this.data.band);
    const next = this.data.band >= 9 ? 5 : this.data.band + 1;
    this.setData({ band: next });
    this.loadDueWords();
  },

  loadDueWords() {
    const app = getApp();
    this.setData({
      loading: true, finished: false, currentIndex: 0,
      userAnswer: '', correctCount: 0, progressPercent: 0
    });
    console.log('[quiz loadDueWords] band=', this.data.band);
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/review/due',
      method: 'GET',
      data: { band: this.data.band, limit: 10 },
      header: this._authHeader(),
      success: (res) => {
        console.log('[quiz loadDueWords] response status=', res.statusCode, 'data=', JSON.stringify(res.data).slice(0, 200));
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const items = body.items || body.due_words || body.words || [];
          console.log('[quiz loadDueWords] items count=', items.length, 'words=', items.map(i => i.word).join(','));
          this.setData({ questions: items });
          if (items.length === 0) {
            wx.showToast({ title: '今日无待复习单词', icon: 'success' });
          }
        } else {
          wx.showToast({ title: '加载复习单词失败', icon: 'none' });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ loading: false })
    });
  },

  onAnswerInput(e) {
    this.setData({ userAnswer: e.detail.value });
  },

  submitAnswer() {
    const { questions, currentIndex, userAnswer, mode } = this.data;
    if (!questions[currentIndex]) return;
    const current = questions[currentIndex];
    const answer = (userAnswer || '').trim().toLowerCase();
    const correct = (mode === 'en2zh' ? current.meaning : current.word).toLowerCase();
    const isCorrect = !!answer && (answer === correct || correct.indexOf(answer) >= 0 || answer.indexOf(correct) >= 0);

    this.setData({
      showResult: true,
      isCorrect: isCorrect,
      correctAnswer: correct,
      resultIcon: isCorrect ? '✅' : '❌',
      resultTitle: isCorrect ? '答对了！' : '答错了',
      resultTitleClass: isCorrect ? 'result-correct' : 'result-wrong'
    });

    this._submitResult(current, isCorrect, userAnswer, mode);
    setTimeout(() => this.goNext(isCorrect), 1200);
  },

  _submitResult(current, isCorrect, userAnswer, mode) {
    const app = getApp();
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/vocab/quiz/submit',
      method: 'POST',
      data: {
        word: current.word,
        user_answer: userAnswer || '',
        correct: isCorrect,
        mode: mode || 'en2zh'
      },
      header: Object.assign({ 'Content-Type': 'application/json' }, this._authHeader()),
      fail: () => {}
    });
  },

  skip() {
    this.goNext(false);
  },

  goNext(isCorrect) {
    const { questions, currentIndex, correctCount } = this.data;
    const newCorrectCount = correctCount + (isCorrect ? 1 : 0);
    const nextIdx = currentIndex + 1;

    if (nextIdx >= questions.length) {
      this.setData({
        finished: true,
        correctCount: newCorrectCount,
        showResult: false,
        userAnswer: '',
        progressPercent: 100
      });
      wx.showToast({ title: '本轮完成！', icon: 'success' });
    } else {
      this.setData({
        currentIndex: nextIdx,
        correctCount: newCorrectCount,
        userAnswer: '',
        showResult: false,
        progressPercent: Math.round((nextIdx + 1) * 100 / questions.length)
      });
    }
  },

  restart() {
    this.loadDueWords();
  },

  _authHeader() {
    const token = wx.getStorageSync('ib_access_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }
});