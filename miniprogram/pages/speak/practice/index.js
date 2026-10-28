// pages/speak/practice/index.js — 口语对练（v3.9+ / 2026-09-20）
//
// 流程：
//   1. 页面加载 → 自动调 /api/wx/speak/practice/start 拿题（按当前 part）
//   2. 用户点大麦克风图标 → 授权麦克风 → 开始录音（wx.getRecorderManager）
//   3. 用户点停止 → 录音文件暂存本地
//   4. 用户点提交 → 用 wx.uploadFile 上传到 /api/wx/speak/practice/submit（multipart/form-data）
//   5. 后端返回 4 维 Band 分数 + 转写 + 纠错 + 建议
//   6. 用户点"下一题" → 重新调 start 拿新题
//
// v4.0 修复：真机点「开始练习」报 "start fail:api..."
// 根因：开了 __usePrivacyCheck__ 但没声明录音相关隐私接口，
//      RecorderManager.start 直接被微信拦掉。
//      修法：① app.json 补 permission(scope.record) + requiredPrivateInfos
//            ② 录音前显式 wx.authorize({scope:'scope.record'}) 并给出可读错误
//      注意：mp 后台的《用户隐私保护指引》也必须声明「访问你的麦克风」，
//            否则 authorize 会报 "api scope is not declared in the privacy agreement"。

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
  //
  // 微信隐私接口调用顺序：
  //   1. wx.requirePrivacyAuthorize —— 拿到《用户隐私保护指引》的用户同意
  //      （2023-09 后所有敏感接口都需要；已在 app.json 开 __usePrivacyCheck__）
  //   2. wx.authorize({scope:'scope.record'}) —— 拿到麦克风权限
  //      （用户拒绝过就要引导到设置页）
  //   3. RecorderManager.start()
  //
  // 之前只做了第 1 步就直接 start()，真机上被微信拦掉报 "start fail:api..."
  startRecord() {
    const that = this;

    // 第 1 步：隐私协议同意
    const afterPrivacy = () => {
      // 第 2 步：麦克风权限
      that._requestRecordAuth();
    };

    if (wx.requirePrivacyAuthorize) {
      wx.requirePrivacyAuthorize({
        success: afterPrivacy,
        fail: () => {
          wx.showModal({
            title: '需要隐私授权',
            content: '口语对练需要使用麦克风录音，请在弹出的授权界面同意隐私保护指引。',
            showCancel: false,
            confirmText: '知道了'
          });
        }
      });
    } else {
      afterPrivacy();
    }
  },

  // 申请麦克风权限
  _requestRecordAuth() {
    const that = this;

    const start = () => {
      that._doStartRecord();
    };

    // 已授权过的情况：直接调 authorize 会立刻 success
    wx.authorize({
      scope: 'scope.record',
      success: start,
      fail: (err) => {
        const msg = (err && err.errMsg) || '';
        // 用户之前拒绝过 → 引导到设置页手动开启
        if (msg.indexOf('auth deny') >= 0 || msg.indexOf('authorize:fail') >= 0) {
          wx.showModal({
            title: '需要麦克风权限',
            content: '口语对练需要麦克风权限才能录音。\n点击「去设置」开启麦克风权限。',
            confirmText: '去设置',
            cancelText: '取消',
            success: (res) => {
              if (res.confirm) {
                wx.openSetting({
                  success: (setting) => {
                    if (setting.authSetting && setting.authSetting['scope.record']) {
                      start();
                    } else {
                      wx.showToast({ title: '仍未开启麦克风权限', icon: 'none' });
                    }
                  }
                });
              }
            }
          });
        } else {
          wx.showModal({
            title: '录音不可用',
            content: '无法开启麦克风（' + msg.slice(0, 80) + '）。\n请确认小程序《用户隐私保护指引》已声明「访问你的麦克风」。',
            showCancel: false,
            confirmText: '知道了'
          });
        }
      }
    });
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
      // 真机上最常见的失败原因：隐私接口未声明 / 用户未授权
      const msg = (err && err.errMsg) || '未知错误';
      wx.showModal({
        title: '录音失败',
        content: msg + '\n\n若提示 scope/privacy 相关错误，请在 mp 后台《用户隐私保护指引》补充「访问你的麦克风」。',
        showCancel: false,
        confirmText: '知道了'
      });
      that.setData({ recording: false });
      that._stopTimer();
    });

    // 配置：60 秒上限，16kHz 采样，mp3 格式（兼容 Whisper）
    recorderManager.start({
      duration: 60000,
      sampleRate: 16000,
      numberOfChannels: 1,
      format: 'mp3',
      fail: (err) => {
        wx.showModal({
          title: '录音启动失败',
          content: (err && err.errMsg) || '未知错误',
          showCancel: false,
          confirmText: '知道了'
        });
      }
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
            wx.showModal({
              title: '评分失败',
              content: msg,
              showCancel: false,
              confirmText: '知道了'
            });
          }
        } catch (e) {
          wx.showModal({
            title: '响应解析失败',
            content: String(e && e.message ? e.message : e).slice(0, 200),
            showCancel: false,
            confirmText: '知道了'
          });
        }
      },
      fail: (err) => {
        wx.showModal({
          title: '上传失败',
          content: (err && err.errMsg) || '网络异常',
          showCancel: false,
          confirmText: '知道了'
        });
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
