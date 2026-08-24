// SKILL/speak/index.js — 口语对练
const axios = require('axios');
const API_BASE = 'https://api.your-domain.cn';

module.exports = {
  async start_practice(input) {
    const resp = await axios.post(
      `${API_BASE}/api/wx/speak/practice/start?part=${input.part || ''}`,
      {},
      { headers: { 'Authorization': `Bearer ${input._token || ''}` } }
    );
    return resp.data;
  },

  async submit_practice(input) {
    const form = new FormData();
    form.append('session_id', input.session_id);
    form.append('part', String(input.part));
    form.append('topic_id', String(input.topic_id));
    form.append('topic_name', input.topic_name);
    form.append('question', input.question);
    form.append('actual_duration_sec', String(input.actual_duration_sec || 0));
    form.append('vocab_hints', (input.vocab_hints || []).join(','));
    form.append('sample_answer', input.sample_answer || '');
    // input.audio 是 base64 字符串或文件路径
    if (input.audio_base64) {
      const buf = Buffer.from(input.audio_base64, 'base64');
      form.append('audio', buf, 'recording.webm');
    }
    const resp = await axios.post(`${API_BASE}/api/wx/speak/practice/submit`, form, {
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },

  async get_history(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/speak/practice/history`, {
      params: { part: input.part, page: input.page || 1, size: input.size || 20 },
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },

  async get_record(input) {
    const resp = await axios.get(`${API_BASE}/api/wx/speak/practice/${input.record_id}`, {
      headers: { 'Authorization': `Bearer ${input._token || ''}` },
    });
    return resp.data;
  },
};