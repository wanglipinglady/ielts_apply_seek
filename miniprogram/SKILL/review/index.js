// SKILL/review/index.js — 艾宾浩斯复习
const axios = require('axios');
const API_BASE = 'https://ielts.wanglipingresume.com';

module.exports = {
  async get_due_words(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/study/review/due`, {
      params: { band: input.band, limit: input.limit || 50 },
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },

  async submit_review(input) {
    const resp = await axios.post(
      `${API_BASE}/api/wx/study/review/submit`,
      { word: input.word, correct: input.correct },
      { headers: { 'Authorization': `Bearer ${input._token || ''}` } }
    );
    return resp.data;
  },

  async get_mistakes(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/study/mistakes`, {
      params: { limit: input.limit || 50 },
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },
};