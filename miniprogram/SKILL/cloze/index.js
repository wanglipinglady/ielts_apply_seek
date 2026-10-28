// SKILL/cloze/index.js — 完形填空
const axios = require('axios');
const API_BASE = 'https://ielts.wanglipingresume.com';

module.exports = {
  async generate_cloze(input) {
    const resp = await axios.post(`${API_BASE}/api/wx/cloze/generate`, {
      band: input.band, topic: input.topic, count: input.count || 5,
    }, { headers: { 'Authorization': `Bearer ${input._token || ''}` } });
    return resp.data;
  },

  async submit_answer(input) {
    const resp = await axios.post(`${API_BASE}/api/wx/cloze/answer`, {
      question_id: input.question_id, user_answer: input.user_answer,
    }, { headers: { 'Authorization': `Bearer ${input._token || ''}` } });
    return resp.data;
  },

  async get_stats(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/cloze/stats`, {
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },
};