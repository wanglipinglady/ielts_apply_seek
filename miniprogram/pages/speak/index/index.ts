// pages/speak/index/index.ts — 口语 Tab 首页
// W3 详细填充内容（Whisper 录音 + LLM 评分）
Page({
  data: {
    parts: [
      { id: 1, name: 'Part 1', desc: '日常问答 · 4-5 min', icon: '💬' },
      { id: 2, name: 'Part 2', desc: '话题卡片 · 3-4 min', icon: '🎤' },
      { id: 3, name: 'Part 3', desc: '深度讨论 · 4-5 min', icon: '🤔' },
    ],
  },

  goPart(e: any) {
    const part = e.currentTarget.dataset.part;
    wx.navigateTo({
      url: `/pages/speak/practice/index?part=${part}`,
    });
  },
});