// pages/study/random/index.ts — 抽词子页
import { get } from '../../../utils/request';

interface VocabWord {
  word: string;
  phonetic: string;
  meaning: string;
  pos: string;
  band: number;
}

Page({
  data: {
    band: 7,
    count: 10,
    words: [] as VocabWord[],
    loading: false,
  },
  onLoad() { this.loadRandom(); },
  onBandChange(e: any) {
    this.setData({ band: e.detail.value });
    this.loadRandom();
  },
  onCountChange(e: any) {
    this.setData({ count: e.detail.value });
    this.loadRandom();
  },
  async loadRandom() {
    this.setData({ loading: true });
    try {
      const res = await get<{ words: VocabWord[] }>('/api/wx/study/vocab/random', {
        band: this.data.band,
        count: this.data.count,
      });
      this.setData({ words: res.words, loading: false });
    } catch (e) {
      this.setData({ loading: false });
    }
  },
});