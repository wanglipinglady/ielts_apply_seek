/**
 * utils/request.js — 统一 HTTP 请求封装
 *
 * 功能：
 * - 自动注入 Bearer token
 * - 401 自动跳登录
 * - 错误 toast
 * - GET/POST/upload 三种便捷方法
 */
const API_BASE_URL = (getApp() && getApp().globalData.apiBaseUrl) || 'https://ielts.wanglipingresume.com';

function getAuthHeader() {
  const token = wx.getStorageSync('ib_access_token');
  return token ? { 'Authorization': 'Bearer ' + token } : {};
}

function handle401(res) {
  // 401 表示 token 过期或无效
  wx.showModal({
    title: '登录已过期',
    content: '请重新登录',
    showCancel: false,
    success: function() {
      wx.removeStorageSync('ib_access_token');
      wx.removeStorageSync('ib_refresh_token');
      wx.removeStorageSync('ib_user');
      wx.reLaunch({ url: '/pages/auth/login/index' });
    }
  });
}

function request(method, path, data, extraHeader) {
  const app = getApp() || {};
  const base = app.globalData && app.globalData.apiBaseUrl ? app.globalData.apiBaseUrl : API_BASE_URL;
  return new Promise(function(resolve, reject) {
    const header = Object.assign({ 'Content-Type': 'application/json' }, getAuthHeader(), extraHeader || {});
    wx.request({
      url: base + path,
      method: method,
      data: data || {},
      header: header,
      success: function(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          handle401(res);
          reject(new Error('登录已过期'));
        } else if (res.statusCode === 422) {
          let msg = '请求参数错误';
          if (res.data && Array.isArray(res.data.detail)) {
            msg = res.data.detail.map(function(d) { return d.msg; }).join('; ');
          }
          wx.showToast({ title: msg, icon: 'none' });
          reject(new Error(msg));
        } else {
          wx.showToast({ title: '请求失败 ' + res.statusCode, icon: 'none' });
          reject(new Error('HTTP ' + res.statusCode));
        }
      },
      fail: function(err) {
        wx.showToast({ title: '网络异常（请检查后端是否启动 + 不校验合法域名）', icon: 'none' });
        reject(err);
      }
    });
  });
}

function get(path, query) {
  let url = path;
  if (query && typeof query === 'object') {
    const parts = [];
    Object.keys(query).forEach(function(k) {
      const v = query[k];
      if (v !== undefined && v !== null) {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(v));
      }
    });
    if (parts.length) url += '?' + parts.join('&');
  }
  return request('GET', url);
}

function post(path, data) {
  return request('POST', path, data);
}

module.exports = { get: get, post: post, request: request, getAuthHeader: getAuthHeader };