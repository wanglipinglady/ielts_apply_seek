// pages/auth/login/index.ts — 登录页
import { post } from '../../../utils/request';

const app = getApp() as any;

Page({
  data: {
    nickname: '',
    loading: false,
    errorMsg: '',
  },

  onLoad() {
    // 自动尝试登录（dev 模式 + 自动从 wx.login 拿 code）
    this.doLogin();
  },

  onNicknameInput(e: any) {
    this.setData({ nickname: e.detail.value });
  },

  async doLogin() {
    this.setData({ loading: true, errorMsg: '' });
    try {
      // 1. 调 wx.login 拿临时凭证
      const loginRes = await new Promise<WechatMiniprogram.LoginSuccessCallbackResult>((resolve, reject) => {
        wx.login({
          success: resolve,
          fail: reject,
        });
      });
      const code = loginRes.code;

      if (!code) {
        throw new Error('wx.login 未返回 code（请检查小程序后台 AppID 配置）');
      }

      // 2. 调后端 /api/wx/login 换 token
      // 注意：dev 模式如果没有真实 AppID，前端走 mock（直接用 code 当 openid）
      const body: any = { code };
      if (this.data.nickname) {
        body.nickname = this.data.nickname;
      }

      const res = await post<any>('/api/wx/login', body);

      // 3. 保存 token
      app.saveToken(res.access_token);
      wx.setStorageSync('ib_refresh_token', res.refresh_token);
      app.globalData.user = res.user;

      // 4. 跳到学习 Tab
      wx.switchTab({ url: '/pages/study/index/index' });
    } catch (e: any) {
      this.setData({ errorMsg: e.message || '登录失败' });
      wx.showToast({ title: this.data.errorMsg || '登录失败', icon: 'none', duration: 3000 });
    } finally {
      this.setData({ loading: false });
    }
  },
});