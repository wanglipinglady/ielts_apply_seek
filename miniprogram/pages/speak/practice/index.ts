// pages/speak/practice/index.ts — 口语对练（W3 详细实现）
// W2 仅做骨架：选择 Part 进入页面，显示引导
Page({
  data: {
    part: 1,
    topic: '',
  },

  onLoad(query: any) {
    const part = parseInt(query.part || '1');
    this.setData({ part });
  },
});