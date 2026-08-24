# 微信小程序 AI 生态外部约束核查（截至 2026-08-24）

> 本文档由 W1 启动前的"外部约束核查"任务汇总而成，作为 W1–W8 全周期文档的事实依据。
> 所有结论均来自 developers.weixin.qq.com 官方文档或 P1/P2 公开来源，未核实条目以 [INSUFFICIENT DATA] 标注。

---

## 一、小程序 AI 开发模式（beta）

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 1.1 | "AI 开发模式"是微信官方提供的一套智能开发框架：将小程序功能抽象为"原子接口"+"原子组件"，封装为 `SKILL`，供"小程序 AI"在用户对话中调度 | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 1.2 | 引入"小程序 MCP"协议（不同于标准 MCP，专为小程序上下文重写） | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 1.3 | 申请入口：公众平台 → AI 能力 → AI 开发模式 / 或开发者助手 → 微信 AI 管理 | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 1.4 | **普通开发者账号能否开通**：官方仅写"内测阶段"，未对个人/企业资质做单独说明 [INSUFFICIENT DATA] | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 中 |
| 1.5 | **当前为内测，代码提审暂未开放** | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 1.6 | 配额/计费：官方文档未列 [INSUFFICIENT DATA]；云开发侧"AI 小程序成长计划"有 1 亿/10 亿 Token 免费额度 | https://developer.cloud.tencent.cn/article/2705075 | 低 |
| 1.7 | 模型可选范围 [INSUFFICIENT DATA]：云开发侧主推混元 + DeepSeek，但与"AI 开发模式"非一一对应 | https://docs.cloudbase.net/recipes/add-ai-wechat-miniprogram | 中 |
| 1.8 | **SKILL 总量上限 30 个** | https://developers.weixin.qq.com/miniprogram/dev/ai/integration | 高 |
| 1.9 | SKILL 固定结构：`SKILL.md`（≤16000 字节） + `mcp.json`（≤24000 字节） + `index.js` + `apis/` + `components/`；必须放在独立分包 | https://developers.weixin.qq.com/miniprogram/dev/ai/integration | 高 |
| 1.10 | 支持自定义原子接口（`inputSchema` / `outputSchema` 按 JSON Schema 声明）；支持中间件 `skill.use(Middleware)`；超时上限 300s | https://developers.weixin.qq.com/miniprogram/dev/ai/integration | 高 |
| 1.11 | "全局提示词"使用 `AGENTS.md`（≤10000 字节、非必填） | https://developers.weixin.qq.com/miniprogram/dev/ai/integration | 高 |

---

## 二、小程序 AI 智能体 / SKILL / MCP

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 2.1 | SKILL 定义：一个 SKILL = `SKILL.md`（业务说明） + `mcp.json`（能力声明） + 原子接口与原子组件实现 | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 2.2 | SKILL 与标准 MCP 关系：小程序 MCP 是为小程序上下文重写的专属协议 | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 2.3 | SKILL 挂载方式：在 `app.json` 的 `agent.skills` 数组中声明（`name` / `description` / `path`） | https://developers.weixin.qq.com/miniprogram/dev/ai/integration | 高 |
| 2.4 | "是否所有小程序都能调用"：2026-04-16 起"AI 小程序成长计划"扩展到全行业全类目 | https://www.woshipm.com/ai/6410296.html | 中 |
| 2.5 | 典型规模：成长计划启动 100 天内已有超过 27000 个 AI 小程序加入，个人开发者占比超 70% | https://www.woshipm.com/ai/6410296.html | 中 |
| 2.6 | 官方示例代码：`wechat-miniprogram/ai-mode-demo` | https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html | 高 |
| 2.7 | 演示回流：AI 调度原子接口 → 返回"账号卡片" → 用户点击 → `wx.onAgentHandoff` 接力到指定 Page | https://developers.weixin.qq.com/miniprogram/dev/ai/integration | 高 |

---

## 三、微信 ClawBot / iLink 个人接入

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 3.1 | **ClawBot 形态**：微信原生插件（Plugin），入口「微信 → 我 → 设置 → 插件」；底层协议 iLink（智联），官方接入域 `ilinkai.weixin.qq.com`，由腾讯 OpenClaw 框架开放 | https://blog.csdn.net/u010662249/article/details/159354987 | 高 |
| 3.2 | **个人开发者可接入**：通过 `npx cc-weixin` 等桥接器扫码登录个人微信 | https://blog.csdn.net/kilohester/article/details/161430731 | 中 |
| 3.3 | **与小程序 AI 开发模式关系**：ClawBot 只是消息转发工具，**无法调用微信小程序 API 或访问小程序数据** | https://news.qiniu.com/archives/1774342011600 | 高 |
| 3.4 | 协议代际：2026-03-18 QClaw 升级；2026-03-22 微信 8.0.70 起通过 ClawBot 原生支持 OpenClaw | https://blog.csdn.net/u010662249/article/details/159354987 | 中 |
| 3.5 | 功能边界：支持文本/图片/视频/文件双向；不支持企业微信、位置、小程序卡片、红包/转账、朋友圈、添加/删除好友、音视频通话 | https://news.qiniu.com/archives/1774342011600 | 高 |
| 3.6 | 合规风险：iLink 协议属微信内部协议，官方明确禁止第三方使用；高频/批量自动回复会被风控 | https://news.qiniu.com/archives/1774342011600 | 中 |

---

## 四、小程序开放服务类目 · 教育

### 4a) 教育-在线视频课程对个人开发者的开放度

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 4.1 | 资质 5 选 1：公立学校 / 培训机构办学许可证 / 全国校外教育培训监管平台备案 / 教育部门批准文件 / 信息网络传播视听节目许可证 | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |
| 4.2 | 该类目**对个人主体不开放** | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |
| 4.3 | 适用于教育机构（学历教育学校 / 学历培训机构 / 非学科类培训机构）提供网课、在线培训、讲座等 | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |

### 4b) 雅思备考可挂靠的近似类目

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 4.4 | 教育服务下与语言/备考接近的非个人主体类目：课程销售 / 课程销售平台 / 成人技能培训 / 学历教育（培训机构）/ 出国留学 | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |
| 4.5 | 「课程销售」资质：非经营性互联网信息服务备案核准 + 经营范围含"教育咨询服务" | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |
| 4.6 | 「课程销售平台」资质：增值电信业务经营许可证（含"在线数据处理与交易处理业务"） | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |
| 4.7 | 「成人技能培训」资质：3 选 1（办学许可证 / 人社备案 / 事业单位法人证书） | https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN | 高 |
| 4.8 | **个人主体可挂靠**的近似类目：工具-效率、工具-图片音视频处理、教育-辅助工具（第三方汇总） | https://blog.csdn.net/yangguangxiadewo/article/details/158381880 | 中 |

### 4c) 低门槛绕开资质的合规路径

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 4.9 | 个人主体可绕开办学许可的核心组合：纯工具 + 不收费 + 不发课程内容；任何"在线培训收费"或"网课直播课程"都会触发资质 | https://blog.csdn.net/yangguangxiadewo/article/details/158381880 | 中 |
| 4.10 | 流量主开通门槛：累计 UV ≥ 1000 且无违规；个人主体不能用微信支付 / 卡券 / 直播 / 虚拟支付 | https://blog.csdn.net/yangguangxiadewo/article/details/158381880 | 中 |
| 4.11 | 个人严禁涉足清单：金融 / 医疗 / 新闻 / 社交 / 婚恋 / 视频音频聚合 / 电商 / 政务 / 深度合成 AI 生成内容等 | https://blog.csdn.net/yangguangxiadewo/article/details/158381880 | 高 |

### 4d) 2025–2026 合规要求

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 4.12 | 2026-01-23 网信办等八部门《可能影响未成年人身心健康的网络信息分类办法》 | http://news.cctv.cn/2026/01/23/ARTIoHezdaoQlRVRMJWHMivp260123.shtml | 高 |
| 4.13 | 2026-07-13 微信珊瑚安全微短剧违规处置公告：AI 生成内容与真人实拍/动画采用同一审核标尺 | https://www.163.com/dy/article/L23BH13F0517CABB.html | 中 |
| 4.14 | AI 教育产品合规三大红线：内容不得违规 / 学科类培训遵守双减 / 不得违规采集未成年人数据 | https://m.sohu.com/a/1065966707_120189950/ | 中 |
| 4.15 | 微信《平台常见拒绝情形》3.2.8.10：禁止妨害未成年人身心健康的内容 | https://developers.weixin.qq.com/miniprogram/product/reject | 高 |

---

## 五、2026 微信小程序开发大赛

| # | 事实 | 来源 URL | 置信度 |
|---|------|---------|--------|
| 5.1 | 主办：微信小程序团队 + WAIC Future Tech；主题"与 AI 共生" | https://contest.weixin.qq.com/eventDetails?id=4598379302114656257 | 高 |
| 5.2 | 赛程：7/17 启动报名 → 10/17 提报截止 → 10/28 线上初审 → 11 月上中旬分赛区决赛 → 11 月底总决赛 | 同上 | 高 |
| 5.3 | **49 万元奖金分配**：一等奖 1 组 × 10 万 / 二等奖 3 组 × 5 万 / 三等奖 6 组 × 3 万 / 优秀 AI 创新作品 3 组 × 2 万（税前合计 49 万） | 同上 | 高 |
| 5.4 | **五大赛区**：东部 / 南部 / 西部 / 北部 / 海外 | 同上 | 高 |
| 5.5 | **6 项提报材料**：① 参赛者身份证件；② 小程序名称；③ AppID；④ 小程序二维码；⑤ 小程序说明文档 PDF；⑥ 参赛授权书 PDF/图片 | 同上 | 高 |
| 5.6 | **评审四维**：产品实用性、产品创新性、用户体验感、作品完整度 | 同上 | 高 |
| 5.7 | **评审四维具体权重打分 [INSUFFICIENT DATA]**（规程 PDF 未在本次核查中打开） | — | 低 |
| 5.8 | 参赛资质：单人 / 团队（≤3 人）；每位参赛者实名信息仅可报名 1 份作品；全球开发者开放报名 | 同上 | 高 |
| 5.9 | 个人 / 团队 / 企业 [INSUFFICIENT DATA]（规程 PDF 未读取） | — | 低 |
| 5.10 | 知识产权归属 [INSUFFICIENT DATA]（规程 PDF 未读取） | — | 低 |
| 5.11 | 是否允许使用外部大模型 API [INSUFFICIENT DATA]（章程仅写"鼓励参赛者合理应用人工智能相关技术"） | — | 中 |
| 5.12 | 作品关键合规：① 7/17 前已上线的不属本次大赛作品；② 比赛期间必须经微信公众平台正式上线；③ 命题不限，必须功能完整 | 同上 | 高 |

---

## 六、待补充 [INSUFFICIENT DATA] 项汇总

| 编号 | 字段 | 后续补充路径 |
|------|------|-------------|
| 1.4 | AI 开发模式是否对普通开发者账号开放 | 实操时登录公众平台确认 |
| 1.6 | AI 开发模式配额/计费 | 实操申请时获取最新政策 |
| 1.7 | AI 开发模式可调用模型清单 | 实操申请时确认 |
| 4.8 | "教育-辅助工具"在个人主体「开放类目」表的官方单独列示 | 申请时实测 |
| 5.7 | 大赛评审四维打分权重 | 打开赛事规程 PDF |
| 5.9 | 企业队 / 团队资格细则 | 打开赛事规程 PDF |
| 5.10 | IP 归属与作品商用条款 | 打开赛事规程 PDF |
| 5.11 | 大赛章程对外部大模型 API 的明文态度 | 打开赛事规程 PDF |

---

## 参考资料来源（汇总）

1. https://developers.weixin.qq.com/miniprogram/dev/ai/guide.html
2. https://developers.weixin.qq.com/miniprogram/dev/ai/integration
3. https://www.woshipm.com/ai/6410296.html
4. https://blog.csdn.net/u010662249/article/details/159354987
5. https://blog.csdn.net/kilohester/article/details/161430731
6. https://news.qiniu.com/archives/1774342011600
7. https://developers.weixin.qq.com/miniprogram/product/material/?lang=zh_CN
8. https://developers.weixin.qq.com/miniprogram/product/reject
9. https://blog.csdn.net/yangguangxiadewo/article/details/158381880
10. http://news.cctv.cn/2026/01/23/ARTIoHezdaoQlRVRMJWHMivp260123.shtml
11. https://www.163.com/dy/article/L23BH13F0517CABB.html
12. https://contest.weixin.qq.com/eventDetails?id=4598379302114656257
13. https://h5.ifeng.com/c/vivoArticle/v002OlhC8UgbBkkcmca8NKzw3Y6ZB75uFnHgV-_jzZ2AGM2o__
14. https://developer.cloud.tencent.cn/article/2705075
15. https://docs.cloudbase.net/recipes/add-ai-wechat-miniprogram
