// SKILL/vocab/index.js — 微信 AI 调度入口
// 微信小程序 AI 模式通过 mcp.json 找到这个文件
// AI 调用时直接转发到后端 FastAPI

const axios = require('axios');

// 运行时由微信注入；后端 API base URL 配置在 app.js
const API_BASE = 'https://api.your-domain.cn';

module.exports = {
  /**
   * list_vocab: 列词库
   * input: { band?, topic?, page, per_page }
   */
  async list_vocab(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/study/vocab/list`, {
      params: input,
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },

  /**
   * random_vocab: 随机抽 N 个词
   * input: { band?, count }
   */
  async random_vocab(input) {
    const resp = await axios.post(
      `${API_BASE}/api/wx/study/vocab/random`,
      { band: input.band, count: input.count },
      { headers: { 'Authorization': `Bearer ${input._token || ''}` } }
    );
    return resp.data;
  },

  /**
   * submit_quiz: 提交测验答案
   * input: { word, user_answer, correct, mode }
   */
  async submit_quiz(input) {
    const resp = await axios.post(
      `${API_BASE}/api/wx/study/vocab/quiz/submit`,
      {
        word: input.word,
        user_answer: input.user_answer,
        correct: input.correct,
        mode: input.mode || 'en2zh',
      },
      { headers: { 'Authorization': `Bearer ${input._token || ''}` } }
    );
    return resp.data;
  },
};