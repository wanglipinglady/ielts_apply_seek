// pages/speak/practice/index.js — 口语对练（v3.9+ / 2026-09-20）
//
// 流程：
//   1. 页面加载 → 自动调 /api/wx/speak/practice/start 拿题（按当前 part）
//   2. 用户点大麦克风图标 → 开始录音（wx.getRecorderManager）
//   3. 用户点停止 → 录音文件暂存本地
//   4. 用户点提交 → 用 wx.uploadFile 上传到 /api/wx/speak/practice/submit（multipart/form-data）
//   5. 后端返回 4 维 Band 分数 + 转写 + 纠错 + 建议
//   6. 用户点"下一题" → 重新调 start 拿新题

const app = getApp();

Page({
  data: {
    part: 1,
    activePart1Class: 'active',
    activePart2Class: '',
    activePart3Class: '',
    sessionId: '',
    topic: '',
    question: '',
    vocab: [],
    tips: '',
    sampleAnswer: '',
    loading: false,
    loadingText: '',
    recording: false,
    recordTime: 0,
    recordTimeText: '00:00',
    audioPath: '',
    duration: 0,
    durationText: '00:00',
    feedback: null,
    feedbacked: false,
    recorderManager: null,
    timer: null,
    history: []
  },

  onLoad(options) {
    if (options && options.part) {
      const part = parseInt(options.part);
      if (part >= 1 && part <= 3) {
        this.setData({ part: part });
      }
    }
    // 自动加载题目
    this.startPractice();
  },

  onUnload() {
    this._stopTimer();
    this._cleanupRecorder();
  },

  onPartChange(e) {
    const part = parseInt(e.currentTarget.dataset.part);
    this.setData({
      part: part,
      activePart1Class: part === 1 ? 'active' : '',
      activePart2Class: part === 2 ? 'active' : '',
      activePart3Class: part === 3 ? 'active' : ''
    });
    this.startPractice();
  },

  // 加载题目
  startPractice() {
    const app = getApp();
    this.setData({
      loading: true,
      loadingText: '正在加载题目...',
      feedback: null,
      feedbacked: false,
      audioPath: '',
      recording: false
    });
    const token = wx.getStorageSync('ib_access_token');
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/speak/practice/start',
      method: 'POST',
      data: { part: this.data.part },
      header: token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const data = res.data || {};
          this.setData({
            sessionId: data.session_id || '',
            topic: data.topic || '',
            question: data.question || '',
            vocab: data.vocab || [],
            tips: data.tips || '',
            sampleAnswer: data.sample_answer || '',
            part: data.part || this.data.part
          });
        } else if (res.statusCode === 404) {
          wx.showToast({ title: '题库为空', icon: 'none' });
        } else {
          wx.showToast({ title: '加载题目失败 ' + res.statusCode, icon: 'none' });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ loading: false, loadingText: '' })
    });
  },

  // 开始录音（入口）
  // 微信要求：调用隐私接口（麦克风）前必须先获得用户对隐私协议的同意
  startRecord() {
    const that = this;
    if (wx.requirePrivacyAuthorize) {
      wx.requirePrivacyAuthorize({
        success: () => { that._doStartRecord(); },
        fail: () => {
          wx.showToast({ title: '需要同意隐私协议才能录音', icon: 'none' });
        }
      });
    } else {
      // 兼容低版本基础库（无隐私接口）
      that._doStartRecord();
    }
  },

  // 实际录音逻辑
  _doStartRecord() {
    const that = this;
    const recorderManager = wx.getRecorderManager();
    this.setData({ recorderManager: recorderManager });

    recorderManager.onStart(() => {
      that.setData({ recording: true, recordTime: 0 });
      that._startTimer();
      wx.showToast({ title: '开始录音...', icon: 'none', duration: 1000 });
    });

    recorderManager.onStop((res) => {
      that.setData({
        recording: false,
        audioPath: res.tempFilePath,
        duration: Math.round(res.duration / 1000)
      });
      that._stopTimer();
      that._formatDuration();
    });

    recorderManager.onError((err) => {
      wx.showToast({ title: '录音失败：' + (err.errMsg || '未知错误'), icon: 'none' });
      that.setData({ recording: false });
      that._stopTimer();
    });

    // 配置：60 秒上限，16kHz 采样，mp3 格式（兼容 Whisper）
    recorderManager.start({
      duration: 60000,
      sampleRate: 16000,
      numberOfChannels: 1,
      format: 'mp3'
    });
  },

  // 停止录音
  stopRecord() {
    if (this.data.recorderManager) {
      this.data.recorderManager.stop();
    }
  },

  // 重新录制
  resetRecord() {
    this.setData({
      audioPath: '',
      duration: 0,
      durationText: '00:00',
      feedback: null,
      feedbacked: false
    });
  },

  // 计时器
  _startTimer() {
    const that = this;
    const timer = setInterval(() => {
      const newTime = that.data.recordTime + 1;
      const mm = String(Math.floor(newTime / 60)).padStart(2, '0');
      const ss = String(newTime % 60).padStart(2, '0');
      that.setData({
        recordTime: newTime,
        recordTimeText: mm + ':' + ss
      });
    }, 1000);
    this.setData({ timer: timer });
  },

  _stopTimer() {
    if (this.data.timer) {
      clearInterval(this.data.timer);
      this.setData({ timer: null });
    }
  },

  _formatDuration() {
    const d = this.data.duration;
    const mm = String(Math.floor(d / 60)).padStart(2, '0');
    const ss = String(d % 60).padStart(2, '0');
    this.setData({ durationText: mm + ':' + ss });
  },

  // 提交录音评分
  submitRecording() {
    if (!this.data.audioPath) {
      wx.showToast({ title: '请先录音', icon: 'none' });
      return;
    }
    if (!this.data.sessionId) {
      wx.showToast({ title: '会话已过期，请重新加载', icon: 'none' });
      return;
    }

    const app = getApp();
    const token = wx.getStorageSync('ib_access_token');
    this.setData({ loading: true, loadingText: 'AI 评分中...（Whisper 转写 + LLM 评分）' });

    // 用 wx.uploadFile 上传 multipart/form-data
    wx.uploadFile({
      url: app.globalData.apiBaseUrl + '/api/wx/speak/practice/submit',
      filePath: this.data.audioPath,
      name: 'audio',
      formData: {
        session_id: this.data.sessionId,
        part: this.data.part,
        topic_id: this.data.vocab && this.data.vocab.length > 0 ? 1 : 0,
        topic_name: this.data.topic,
        question: this.data.question,
        actual_duration_sec: this.data.duration,
        vocab_hints: (this.data.vocab || []).join(','),
        sample_answer: this.data.sampleAnswer
      },
      header: token ? { 'Authorization': 'Bearer ' + token } : {},
      success: (res) => {
        try {
          const body = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
          if (res.statusCode >= 200 && res.statusCode < 300 && body) {
            this.setData({
              feedback: body,
              feedbacked: true
            });
            wx.showToast({ title: '评分完成', icon: 'success' });
          } else {
            const msg = (body && body.detail) || ('评分失败 ' + res.statusCode);
            wx.showToast({ title: msg, icon: 'none' });
          }
        } catch (e) {
          wx.showToast({ title: '响应解析失败', icon: 'none' });
        }
      },
      fail: (err) => {
        wx.showToast({ title: '上传失败：' + (err.errMsg || '网络异常'), icon: 'none' });
      },
      complete: () => {
        this.setData({ loading: false, loadingText: '' });
      }
    });
  },

  // 清理录音器
  _cleanupRecorder() {
    if (this.data.recorderManager) {
      try {
        this.data.recorderManager.stop();
      } catch (e) {}
      this.setData({ recorderManager: null });
    }
  },

  // 下一题
  nextQuestion() {
    this.setData({ feedback: null, feedbacked: false, audioPath: '', duration: 0 });
    this.startPractice();
  },

  // 重新录制当前题（不抽新题，复用现有 sessionId + topic + question + vocab）
  retryCurrent() {
    this.setData({
      feedback: null,
      feedbacked: false,
      audioPath: '',
      duration: 0,
      durationText: '00:00',
      recordTime: 0,
      recordTimeText: '00:00',
      recording: false,
      loading: false,
      loadingText: ''
    });
    this._stopTimer();
  },

  // 跳历史记录（占位，可后续接入 /api/wx/speak/practice/history）
  goHistory() {
    wx.showToast({ title: '历史记录开发中', icon: 'none' });
  }
});