// pages/study/index/index.ts — 学习 Tab 首页
// v3.9+ / 2026-08-24
import { get } from '../../../utils/request';

interface VocabWord {
  word: string;
  phonetic: string;
  meaning: string;
  pos: string;
  band: number;
  topic: string;
}

interface VocabListResp {
  words: VocabWord[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

const app = getApp() as any;

Page({
  data: {
    activeTab: 'browse',  // browse / random / quiz
    words: [] as VocabWord[],
    total: 0,
    page: 1,
    per_page: 10,
    band: 7,
    loading: false,
    user: null as any,
  },

  onLoad() {
    this.setData({ user: app.globalData.user });
    this.loadVocabList();
  },

  onShow() {
    // 刷新用户信息
    this.setData({ user: app.globalData.user });
  },

  onPullDownRefresh() {
    this.loadVocabList().then(() => wx.stopPullDownRefresh());
  },

  /** 切换 Tab */
  switchTab(e: any) {
    this.setData({ activeTab: e.currentTarget.dataset.tab });
    if (e.currentTarget.dataset.tab === 'browse' && this.data.words.length === 0) {
      this.loadVocabList();
    }
  },

  /** 切换 Band */
  onBandChange(e: any) {
    this.setData({ band: e.detail.value, page: 1 }, () => {
      this.loadVocabList();
    });
  },

  /** 加载词库列表 */
  async loadVocabList() {
    this.setData({ loading: true });
    try {
      const res = await get<VocabListResp>('/api/wx/study/vocab/list', {
        band: this.data.band,
        page: this.data.page,
        per_page: this.data.per_page,
      });
      this.setData({
        words: res.words,
        total: res.total,
        total_pages: res.total_pages,
        loading: false,
      });
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  /** 加载更多 */
  onReachBottom() {
    if (this.data.page < this.data.total_pages) {
      this.setData({ page: this.data.page + 1 }, () => {
        this.loadMore();
      });
    }
  },

  async loadMore() {
    try {
      const res = await get<VocabListResp>('/api/wx/study/vocab/list', {
        band: this.data.band,
        page: this.data.page,
        per_page: this.data.per_page,
      });
      this.setData({
        words: [...this.data.words, ...res.words],
      });
    } catch (e) {
      // ignore
    }
  },

  /** 跳到抽词 Tab */
  goRandom() {
    this.setData({ activeTab: 'random' });
    this.onRandomTap();
  },

  /** 抽 5 个词 */
  async onRandomTap() {
    this.setData({ loading: true });
    try {
      const res = await get<{ words: VocabWord[]; count: number }>(
        '/api/wx/study/vocab/random',
        { band: this.data.band, count: 5 }
      );
      this.setData({ words: res.words, loading: false });
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  /** 跳测验 Tab */
  goQuiz() {
    wx.navigateTo({ url: '/pages/study/quiz/index' });
  },
});