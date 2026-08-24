// pages/review/mistakes/index.ts — 错词本二级页
import { get, post } from '../../../utils/request';

interface MistakeItem {
  word: string;
  meaning: string;
  wrong_count: number;
  last_reviewed: string;
}

Page({
  data: {
    mistakes: [] as MistakeItem[],
    count: 0,
    loading: false,
  },

  onLoad() {
    this.loadMistakes();
  },

  onPullDownRefresh() {
    this.loadMistakes().then(() => wx.stopPullDownRefresh());
  },

  async loadMistakes() {
    this.setData({ loading: true });
    try {
      const res = await get<{ mistakes: MistakeItem[]; count: number }>(
        '/api/wx/study/mistakes'
      );
      this.setData({
        mistakes: res.mistakes,
        count: res.count,
        loading: false,
      });
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  /** 标记掌握（清 wrong_count=0，等下次记录时会自动加回 0 但表示已掌握）*/
  async markMastered(e: any) {
    const word = e.currentTarget.dataset.word;
    // 此处简化：UI 上提供「掌握」入口，后端可后续扩展 mark-correct 接口
    wx.showToast({ title: '功能开发中', icon: 'none' });
  },
});