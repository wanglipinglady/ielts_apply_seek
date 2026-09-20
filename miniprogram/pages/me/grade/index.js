// pages/me/grade/index.js — AI 写作批改（v3.9+ / 2026-09-20 修复三元）

const app = getApp();

const ISSUE_TYPE_CLASS = {
  '语法': 'grammar',
  'grammar': 'grammar',
  '词汇': 'lexical',
  'lexical': 'lexical',
  '连贯': 'coherence',
  'coherence': 'coherence',
  '任务回应': 'task_response',
  'task_response': 'task_response',
  '建议': 'suggestion',
  'suggestion': 'suggestion'
};

function mapIssueTypeClass(t) {
  if (!t) return 'suggestion';
  return ISSUE_TYPE_CLASS[t] || 'suggestion';
}

const TOPICS = {
  task1: [
    { tag: '折线图', text: 'The chart shows the proportion of energy from renewable resources between 2000 and 2020. Summarize the information by selecting and reporting the main features.' },
    { tag: '柱状图', text: 'The bar chart illustrates the average weekly hours spent on different activities by full-time and part-time employees. Summarize the information.' },
    { tag: '流程图', text: 'The diagram shows the process of producing chocolate. Write a summary describing the production process.' },
    { tag: '地图', text: 'The maps show the changes in a town from 1990 to present. Summarize the information by selecting and reporting the main features.' }
  ],
  task2: [
    { tag: '教育', text: 'Some people think that children should start school as early as possible. To what extent do you agree or disagree?' },
    { tag: '科技', text: 'With the rapid development of technology, more and more jobs are replaced by machines. Discuss the advantages and disadvantages.' },
    { tag: '环境', text: 'Many people say that we should protect the environment, but few actions are taken. Why is that? What can be done to solve this problem?' },
    { tag: '社会', text: 'In many countries, the number of people living alone is increasing. What are the causes and effects of this trend?' }
  ]
};

const MIN_WORDS = { task1: 150, task2: 250 };

Page({
  data: {
    taskType: 'task2',
    taskTab1Class: '',
    taskTab2Class: 'active',
    topic: '教育',
    topicText: '',
    essay: '',
    wordCount: 0,
    minWords: 250,
    wordStatusClass: 'warn',
    wordStatusText: '字数不足',
    submitDisabled: true,
    submitButtonText: '至少输入 50 字符',
    loading: false,
    showInputArea: true,
    result: null,
    resultTaskLabel: '',
    resultTopicText: '',
    hasAnnotations: false,
    hasSuggestions: false
  },

  onLoad() {
    this._refreshTopic();
  },

  onTaskChange(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({
      taskType: type,
      result: null,
      essay: '',
      wordCount: 0,
      showInputArea: true
    });
    this._refreshTopic();
  },

  _refreshTopic() {
    const topics = TOPICS[this.data.taskType];
    const t = topics[Math.floor(Math.random() * topics.length)];
    this.setData({
      topic: t.tag,
      topicText: t.text,
      minWords: MIN_WORDS[this.data.taskType],
      essay: '',
      wordCount: 0,
      result: null,
      showInputArea: true,
      taskTab1Class: this.data.taskType === 'task1' ? 'active' : '',
      taskTab2Class: this.data.taskType === 'task2' ? 'active' : ''
    });
  },

  onEssayInput(e) {
    const essay = e.detail.value;
    const wordCount = essay.trim() ? essay.trim().split(/\s+/).length : 0;
    const wordStatusClass = wordCount >= this.data.minWords ? 'ok' : 'warn';
    const wordStatusText = wordCount >= this.data.minWords ? '字数达标' : '字数不足';
    const submitDisabled = essay.trim().length < 50;
    const submitButtonText = essay.trim().length < 50 ? '至少输入 50 字符' : '提交 AI 批改';
    this.setData({
      essay: essay,
      wordCount: wordCount,
      wordStatusClass: wordStatusClass,
      wordStatusText: wordStatusText,
      submitDisabled: submitDisabled,
      submitButtonText: submitButtonText
    });
  },

  onSubmit() {
    if (this.data.essay.trim().length < 50) {
      wx.showToast({ title: '请输入至少 50 字符', icon: 'none' });
      return;
    }
    const app = getApp();
    const token = wx.getStorageSync('ib_access_token');
    this.setData({ loading: true, showInputArea: false });

    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/grade/submit',
      method: 'POST',
      header: token ? { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/x-www-form-urlencoded' } : { 'Content-Type': 'application/x-www-form-urlencoded' },
      data: 'essay=' + encodeURIComponent(this.data.essay) + '&task_type=' + encodeURIComponent(this.data.taskType) + '&topic=' + encodeURIComponent(this.data.topic),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const r = body.result || body;
          const bs = r.band_scores || {};
          const normalized = {
            overall_score: r.overall_score || 0,
            task_type: r.task_type || this.data.taskType,
            topic: r.topic || this.data.topic,
            word_count: r.word_count || this.data.wordCount,
            band_scores: {
              task_response: bs.task_response || bs.task_achievement || 0,
              coherence: bs.coherence || 0,
              lexical: bs.lexical_resource || bs.lexical || 0,
              grammar: bs.grammar_range_accuracy || bs.grammar_range || bs.grammar || 0
            },
            annotations: (r.annotations || []).map(function(a) {
              a.annoTypeClass = mapIssueTypeClass(a.issue_type);
              return a;
            }),
            suggestions: r.suggestions || [],
            rewrite: r.rewrite || '',
            error_summary: r.error_summary || null
          };
          const resultTaskLabel = normalized.task_type === 'task1' ? 'Task 1' : 'Task 2';
          const resultTopicText = normalized.topic || this.data.topic;
          const hasAnnotations = normalized.annotations.length > 0;
          const hasSuggestions = normalized.suggestions.length > 0;
          this.setData({
            result: normalized,
            resultTaskLabel: resultTaskLabel,
            resultTopicText: resultTopicText,
            hasAnnotations: hasAnnotations,
            hasSuggestions: hasSuggestions
          });
          wx.showToast({ title: '批改完成', icon: 'success' });
        } else {
          this.setData({ showInputArea: true });
          let msg = '批改失败 ' + res.statusCode;
          if (res.data && res.data.detail) {
            msg = typeof res.data.detail === 'string' ? res.data.detail : JSON.stringify(res.data.detail);
          }
          wx.showToast({ title: msg, icon: 'none' });
        }
      },
      fail: () => {
        this.setData({ showInputArea: true });
        wx.showToast({ title: '网络异常', icon: 'none' });
      },
      complete: () => this.setData({ loading: false })
    });
  },

  onRetry() {
    this._refreshTopic();
  },

  onNewSubmission() {
    wx.showToast({ title: '历史记录功能开发中', icon: 'none' });
  }
});