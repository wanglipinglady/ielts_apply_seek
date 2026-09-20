// pages/speak/index/index.js — 口语 Tab 首页（v3.9+ / 2026-09-19）
const app = getApp();

Page({
  data: {
    parts: [
      { id: 1, name: 'Part 1 · 日常对话', desc: '4-5 分钟自我介绍 + 日常话题', icon: '💬' },
      { id: 2, name: 'Part 2 · 话题卡片', desc: '1 分钟准备 + 2 分钟独白', icon: '🎤' },
      { id: 3, name: 'Part 3 · 深度讨论', desc: '4-5 分钟双向讨论', icon: '🧠' }
    ]
  },

  goPart(e) {
    const part = e.currentTarget.dataset.part;
    wx.navigateTo({ url: '/pages/speak/practice/index?part=' + part });
  }
});