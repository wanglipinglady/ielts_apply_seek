// pages/review/index/index.ts — 复习 Tab 首页（艾宾浩斯核心）
import { get, post } from '../../../utils/request';

interface DueWord {
  word: string;
  meaning: string;
  phonetic: string;
  band: number;
  memory_level: number;
  next_review_at: string;
}

Page({
  data: {
    activeTab: 'today',  // today / mistakes / starred
    dueWords: [] as DueWord[],
    count: 0,
    today: '',
    loading: false,
    band: 0,  // 0 = 全部
    currentIndex: 0,
    isFlipped: false,
  },

  onLoad() {
    this.loadDueWords();
  },

  onShow() {
    // 从错词本 / 收藏页返回时刷新
    this.loadDueWords();
  },

  switchTab(e: any) {
    this.setData({ activeTab: e.currentTarget.dataset.tab });
    if (e.currentTarget.dataset.tab === 'today') {
      this.loadDueWords();
    } else if (e.currentTab === 'mistakes' || e.currentTarget.dataset.tab === 'mistakes') {
      this.loadMistakes();
    }
  },

  async loadDueWords() {
    this.setData({ loading: true });
    try {
      const query: any = {};
      if (this.data.band > 0) query.band = this.data.band;
      const res = await get<{ due_words: DueWord[]; count: number; today: string }>(
        '/api/wx/study/review/due', query
      );
      this.setData({
        dueWords: res.due_words,
        count: res.count,
        today: res.today,
        loading: false,
        currentIndex: 0,
        isFlipped: false,
      });
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  /** 加载错词本 */
  async loadMistakes() {
    wx.navigateTo({ url: '/pages/review/mistakes/index' });
  },

  /** 翻转卡片（显示释义） */
  flipCard() {
    this.setData({ isFlipped: !this.data.isFlipped });
  },

  /** 标记认识 */
  async onKnow() {
    await this.submitReview(true);
  },

  /** 标记不认识 */
  async onDontKnow() {
    await this.submitReview(false);
  },

  async submitReview(correct: boolean) {
    const word = this.data.dueWords[this.data.currentIndex];
    if (!word) return;
    try {
      await post('/api/wx/study/review/submit', {
        word: word.word,
        correct: correct,
      });
    } catch (e) {
      // ignore, continue to next
    }
    // 切到下一个
    this.setData({
      currentIndex: this.data.currentIndex + 1,
      isFlipped: false,
    });
  },
});