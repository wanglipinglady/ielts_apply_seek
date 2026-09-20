// pages/review/mistakes/index.js — 错词本（v3.9+ / 2026-09-19）
const app = getApp();

Page({
  data: {
    mistakes: [],
    loading: false
  },

  onShow() {
    this.loadMistakes();
  },

  loadMistakes() {
    const app = getApp();
    this.setData({ loading: true });
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/mistakes',
      method: 'GET',
      header: this._authHeader(),
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          const body = res.data || {};
          const mistakes = body.mistakes || body.items || [];
          mistakes.forEach(m => {
            m.phonetic = m.phonetic || '';
            m.error_count = m.wrong_count || m.error_count || 0;
            m.band = m.band || 7;
            m.error_count_text = String(m.error_count);
          });
          this.setData({ mistakes: mistakes });
        }
      },
      fail: () => wx.showToast({ title: '网络异常', icon: 'none' }),
      complete: () => this.setData({ loading: false })
    });
  },

  onWordTap(e) {
    const word = e.currentTarget.dataset.word;
    wx.showModal({
      title: word.word,
      content: (word.phonetic || '') + '\n\n' + word.meaning + '\n\n错误次数：' + (word.error_count || 0),
      showCancel: false
    });
  },

  // 移除单个错词：调后端 /api/wx/study/mistakes/{word}/mark-correct
  // 后端会把 learning_records.wrong_count 清 0，再调 /mistakes 时该词不再出现
  onRemove(e) {
    const word = e.currentTarget.dataset.word;
    const that = this;
    wx.showModal({
      title: '移除错词',
      content: '确定要从错词本移除 "' + word.word + '" 吗？\n（若再次答错会重新加入）',
      success: function(res) {
        if (!res.confirm) return;
        wx.request({
          url: app.globalData.apiBaseUrl + '/api/wx/study/mistakes/' + encodeURIComponent(word.word) + '/mark-correct',
          method: 'POST',
          header: that._authHeader(),
          success: function(r) {
            if (r.statusCode >= 200 && r.statusCode < 300 && r.data && r.data.success) {
              const newList = that.data.mistakes.filter(function(w) { return w.word !== word.word; });
              that.setData({ mistakes: newList });
              wx.showToast({ title: '已移除', icon: 'success' });
            } else {
              wx.showToast({ title: '移除失败 ' + r.statusCode, icon: 'none' });
            }
          },
          fail: function() {
            wx.showToast({ title: '网络异常', icon: 'none' });
          }
        });
      }
    });
  },

  // 清空错词本：遍历调 mark-correct
  onClearAll() {
    const that = this;
    if (that.data.mistakes.length === 0) {
      wx.showToast({ title: '错词本已为空', icon: 'none' });
      return;
    }
    wx.showModal({
      title: '清空错词本',
      content: '确定要清空整个错词本吗？此操作不可恢复。\n（共 ' + that.data.mistakes.length + ' 词）',
      success: function(res) {
        if (!res.confirm) return;
        that._clearAllSequential(0, that.data.mistakes.slice());
      }
    });
  },

  // 顺序遍历清空（避免并发请求过多）
  _clearAllSequential(index, list) {
    const that = this;
    if (index >= list.length) {
      that.setData({ mistakes: [] });
      wx.showToast({ title: '已清空', icon: 'success' });
      return;
    }
    const w = list[index];
    wx.request({
      url: app.globalData.apiBaseUrl + '/api/wx/study/mistakes/' + encodeURIComponent(w.word) + '/mark-correct',
      method: 'POST',
      header: that._authHeader(),
      success: function(r) {
        // 单条失败不阻塞，继续清下一条
        if (!(r.statusCode >= 200 && r.statusCode < 300 && r.data && r.data.success)) {
          console.warn('[clearAll] mark-correct failed for', w.word, r.statusCode);
        }
      },
      fail: function() {
        console.warn('[clearAll] network fail for', w.word);
      },
      complete: function() {
        // 从 UI 列表立即移除，提升反馈速度
        const cur = that.data.mistakes.filter(function(x) { return x.word !== w.word; });
        that.setData({ mistakes: cur });
        that._clearAllSequential(index + 1, list);
      }
    });
  },

  _authHeader() {
    const token = wx.getStorageSync('ib_access_token');
    return token ? { 'Authorization': 'Bearer ' + token } : {};
  }
});