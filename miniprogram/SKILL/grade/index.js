// SKILL/grade/index.js — 写作批改
const axios = require('axios');
const API_BASE = 'https://ielts.wanglipingresume.com';

module.exports = {
  async submit_grade(input) {
    const params = new URLSearchParams();
    params.append('essay', input.essay);
    params.append('task_type', input.task_type || 'task2');
    if (input.topic) params.append('topic', input.topic);

    const resp = await axios.post(`${API_BASE}/api/wx/grade/submit`, params, {
      headers: {
        'Authorization': `Bearer ${input._token || ''}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
    });
    return resp.data;
  },

  async get_history(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/grade/history`, {
      params: { limit: input.limit || 20 },
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },

  async get_stats(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/grade/stats`, {
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },
};