// pages/study/quiz/index.ts — 测验子页（单题作答）
import { get, post } from '../../../utils/request';

interface VocabWord {
  word: string;
  phonetic: string;
  meaning: string;
}

Page({
  data: {
    mode: 'en2zh',  // en2zh / zh2en
    band: 7,
    questions: [] as VocabWord[],
    currentIndex: 0,
    userAnswer: '',
    correctCount: 0,
    finished: false,
    loading: false,
  },

  onLoad() {
    this.loadQuestions();
  },

  async loadQuestions() {
    this.setData({ loading: true });
    try {
      // 抽 10 个词做测验
      const res = await get<{ words: VocabWord[] }>(
        '/api/wx/study/vocab/random',
        { band: this.data.band, count: 10 }
      );
      this.setData({
        questions: res.words,
        currentIndex: 0,
        userAnswer: '',
        correctCount: 0,
        finished: false,
        loading: false,
      });
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  onModeChange(e: any) {
    this.setData({ mode: e.detail.value });
    this.loadQuestions();
  },

  onBandChange(e: any) {
    this.setData({ band: e.detail.value });
    this.loadQuestions();
  },

  onAnswerInput(e: any) {
    this.setData({ userAnswer: e.detail.value });
  },

  async submitAnswer() {
    const q = this.data.questions[this.data.currentIndex];
    if (!q) return;
    const correct = this.data.mode === 'en2zh'
      ? this.data.userAnswer.trim().toLowerCase() === q.meaning.split(/[;,；]/)[0].trim().toLowerCase()
      : this.data.userAnswer.trim().toLowerCase() === q.word.toLowerCase();
    try {
      await post('/api/wx/study/vocab/quiz/submit', {
        word: q.word,
        user_answer: this.data.userAnswer,
        correct: correct,
        mode: this.data.mode,
      });
    } catch (e) {
      // ignore
    }
    if (correct) {
      this.setData({ correctCount: this.data.correctCount + 1 });
      wx.showToast({ title: '✓ 正确', icon: 'success' });
    } else {
      wx.showToast({ title: `✗ 答案：${q.meaning}`, icon: 'none', duration: 2000 });
    }
    setTimeout(() => {
      if (this.data.currentIndex + 1 >= this.data.questions.length) {
        this.setData({ finished: true });
      } else {
        this.setData({
          currentIndex: this.data.currentIndex + 1,
          userAnswer: '',
        });
      }
    }, 1500);
  },

  /** 跳过当前题 */
  skip() {
    if (this.data.currentIndex + 1 >= this.data.questions.length) {
      this.setData({ finished: true });
    } else {
      this.setData({
        currentIndex: this.data.currentIndex + 1,
        userAnswer: '',
      });
    }
  },

  /** 重新开始 */
  restart() {
    this.loadQuestions();
  },
});