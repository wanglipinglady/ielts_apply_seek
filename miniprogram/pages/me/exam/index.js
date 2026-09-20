// pages/me/exam/index.js — 考试日历 v3.9+ / 2026-09-20

const app = getApp();

function getNextSaturday() {
  const today = new Date();
  const day = today.getDay();
  const diff = (6 - day + 7) % 7 || 7;
  const next = new Date(today.getTime() + diff * 86400000);
  return next;
}

function pad(n) {
  return n < 10 ? '0' + n : '' + n;
}

function dateToObj(d) {
  return {
    year: d.getFullYear(),
    month: pad(d.getMonth() + 1),
    day: pad(d.getDate()),
    weekday: ['日', '一', '二', '三', '四', '五', '六'][d.getDay()],
    dateStr: d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
  };
}

function diffDays(target) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const t = new Date(target.getTime());
  t.setHours(0, 0, 0, 0);
  return Math.round((t.getTime() - today.getTime()) / 86400000);
}

Page({
  data: {
    exams: [],
    nextExam: null,
    tipText: ''
  },

  onLoad() {
    this._buildExamList();
  },

  onShow() {
    this._buildExamList();
  },

  _buildExamList() {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const next = getNextSaturday();
    const dayAfter = new Date(next.getTime() + 86400000);

    // 构造 4 场考试：上一场 + 今天（虚拟）+ 下一场 + 下下场
    const candidates = [
      { type: 'academic', title: 'IELTS Academic 学术类', dateOffset: -7 },
      { type: 'general', title: 'IELTS General Training 培训类', dateOffset: 7 },
      { type: 'ukvi', title: 'IELTS for UKVI 英国签证类', dateOffset: 14 },
      { type: 'academic', title: 'IELTS Academic 学术类', dateOffset: 21 }
    ];

    const exams = candidates.map((c, i) => {
      const examDate = new Date(today.getTime() + c.dateOffset * 86400000);
      const dObj = dateToObj(examDate);
      const daysFromNow = c.dateOffset;
      return {
        id: 'exam-' + i,
        type: c.type === 'academic' ? 'A 类' : (c.type === 'general' ? 'G 类' : 'UKVI'),
        type_class: c.type,
        title: c.title,
        month: dObj.month + '月',
        day: dObj.day,
        weekday: '周' + dObj.weekday,
        dateStr: dObj.dateStr,
        time: '08:30 - 12:00',
        fee: '¥2,170',
        is_past: daysFromNow < 0,
        is_today: daysFromNow === 0
      };
    });

    // 下一场（未来最早的）
    const upcoming = exams.find(e => !e.is_past);
    let nextExam = null;
    if (upcoming) {
      const daysLeft = diffDays(new Date(upcoming.dateStr));
      const hoursLeft = 24 - new Date().getHours();
      nextExam = {
        title: upcoming.title,
        type: upcoming.type,
        type_class: upcoming.type_class,
        date_label: upcoming.dateStr + ' ' + upcoming.weekday + ' ' + upcoming.time,
        days: daysLeft,
        hours: hoursLeft > 0 ? hoursLeft : 0,
        minutes: 60 - new Date().getMinutes(),
        tip: this._getTipForType(upcoming.type_class)
      };
    }

    this.setData({
      exams: exams,
      nextExam: nextExam,
      tipText: this._getGeneralTip()
    });
  },

  _getTipForType(typeClass) {
    if (typeClass === 'academic') {
      return '学术类：阅读 3 篇学术文章 + 写作 Task 1 图表描述';
    }
    if (typeClass === 'general') {
      return '培训类：阅读生活场景 + 写作 Task 1 书信类';
    }
    return 'UKVI：增加签证类面试环节，建议提前 1 周模拟';
  },

  _getGeneralTip() {
    return '考前 7 天建议每天 1 套全真模拟，重点练习时间分配。官方模考平台：ielts.org/take-a-practice-test';
  }
});