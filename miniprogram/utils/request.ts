/**
 * utils/request.ts — 统一 HTTP 请求封装（v3.9+）
 *
 * 设计：
 * - 自动注入 Authorization: Bearer <token>
 * - 401 自动尝试 refresh_token 一次
 * - 统一错误处理（toast）
 * - 响应字段与 Web 端契约保持一致（access_token / refresh_token / user 等）
 */

const API_BASE_URL = (getApp() as any).globalData.apiBaseUrl;

/** 解析响应：成功返回 data，失败 toast + 抛错 */
function handleResponse<T>(res: WechatMiniprogram.RequestSuccessCallbackResult, resolve: (data: T) => void, reject: (err: any) => void) {
  const status = res.statusCode;
  if (status >= 200 && status < 300) {
    try {
      const body = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
      resolve(body as T);
    } catch (e) {
      reject(new Error('响应解析失败'));
    }
  } else if (status === 401 || status === 403) {
    // 鉴权失败：尝试 refresh
    refreshTokenAndRetry<T>(res, resolve, reject);
  } else {
    wx.showToast({ title: `请求失败 ${status}`, icon: 'none' });
    reject(new Error(`HTTP ${status}`));
  }
}

function refreshTokenAndRetry<T>(origRes: any, resolve: (data: T) => void, reject: (err: any) => void) {
  const refreshToken = wx.getStorageSync('ib_refresh_token');
  if (!refreshToken) {
    // 没 refresh token → 跳登录
    wx.removeStorageSync('ib_access_token');
    wx.reLaunch({ url: '/pages/auth/login/index' });
    reject(new Error('未登录'));
    return;
  }
  // 调 refresh 端点（注意 Cookie 由微信小程序不持久化，必须走 body 或 header）
  wx.request({
    url: `${API_BASE_URL}/api/auth/refresh`,
    method: 'POST',
    header: { 'Authorization': `Bearer ${refreshToken}` },
    success: (refreshRes) => {
      if (refreshRes.statusCode === 200) {
        const body = typeof refreshRes.data === 'string' ? JSON.parse(refreshRes.data) : refreshRes.data;
        wx.setStorageSync('ib_access_token', body.access_token);
        wx.setStorageSync('ib_refresh_token', body.refresh_token);
        // 重试原请求
        // 简化：直接 reject 让调用方重新发起
        wx.showToast({ title: '已刷新，请重试', icon: 'none' });
      }
      reject(new Error('token 已过期'));
    },
    fail: () => reject(new Error('refresh 失败')),
  });
}

/**
 * 通用 POST 请求（带 token 自动注入 + 401 自动刷新）
 */
export function post<T = any>(path: string, body: any): Promise<T> {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('ib_access_token');
    wx.request({
      url: `${API_BASE_URL}${path}`,
      method: 'POST',
      data: body,
      header: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      success: (res) => handleResponse<T>(res, resolve, reject),
      fail: (err) => { wx.showToast({ title: '网络异常', icon: 'none' }); reject(err); },
    });
  });
}

/** 通用 GET 请求 */
export function get<T = any>(path: string, query?: Record<string, any>): Promise<T> {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('ib_access_token');
    let url = `${API_BASE_URL}${path}`;
    if (query) {
      const params = Object.entries(query)
        .filter(([_, v]) => v !== undefined && v !== null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join('&');
      if (params) url += `?${params}`;
    }
    wx.request({
      url,
      method: 'GET',
      header: token ? { 'Authorization': `Bearer ${token}` } : {},
      success: (res) => handleResponse<T>(res, resolve, reject),
      fail: (err) => { wx.showToast({ title: '网络异常', icon: 'none' }); reject(err); },
    });
  });
}

/** 上传文件（用于录音 / 图片） */
export function upload<T = any>(path: string, filePath: string, formData: Record<string, any> = {}): Promise<T> {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('ib_access_token');
    wx.uploadFile({
      url: `${API_BASE_URL}${path}`,
      filePath,
      name: 'file',
      formData,
      header: token ? { 'Authorization': `Bearer ${token}` } : {},
      success: (res) => handleResponse<T>(res as any, resolve, reject),
      fail: (err) => { wx.showToast({ title: '上传失败', icon: 'none' }); reject(err); },
    });
  });
}