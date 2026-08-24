// pages/me/tools/index.ts — 工具集（W4-W5 详细实现）
Page({
  data: {
    tools: [
      { id: 'typing', name: '机考打字', icon: '⌨️', desc: '练习 WPM + 准确率' },
      { id: 'pomodoro', name: '番茄钟', icon: '🍅', desc: '25 min 专注 + 5 min 休息' },
      { id: 'calendar', name: '学习日历', icon: '📅', desc: '每日学习热力图' },
    ],
  },
  goTool(e: any) { wx.showToast({ title: `${e.currentTarget.dataset.name} W4-W5 上线`, icon: 'none' }); },
});