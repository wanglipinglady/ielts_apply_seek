# Spec 沉淀（v3.9 / 2026-09-21）

> 范围：开发过程中形成的约束、规则、标准、规范的集合。让新加入的开发者（或新的 AI session）能立刻对齐。

---

## 1. WXML / WXSS 规范

### 1.1 WXML 关键字限制（强制）

| 不支持 | 替代 |
|---|---|
| 三目 `condition ? a : b` | JS 预计算字段 + `{{precomputedField}}` |
| `<text wx:for>` | `<view wx:for>` 或 `<block wx:for>` |
| `\|\|`、`?.`、函数调用、字符串拼接 | JS 预处理 |
| `<view bindtap>` 真机不响应 | 用 `<button bindtap>` |

### 1.2 WXML 命名规范

- 数据字段用驼峰：`activePart1Class`、`loadingText`
- 类名用 kebab-case：`part-tab active`、`btn-primary`
- 列表项用 `<view wx:for wx:key="*this">` 或具体字段 key

### 1.3 WXSS 规范

- 优先用 flex 布局，不用 float
- flex 容器必须显式声明 `flex-wrap: wrap`（否则内容溢出被压缩）
- button 默认 `display:block + width:100%`，要加 `display: inline-block` 或外层 flex 控制
- 单位用 rpx（750rpx = 屏幕宽），字号也用 rpx
- 颜色用 hex：`#07C160`（主色绿）、`#F56565`（红）、`#1A3A5F`（深蓝标题）

### 1.4 通用组件模式

**统计卡片**：
```html
<view class="stat-card card">
  <text class="stat-num">{{num}}</text>
  <text class="stat-label">{{label}}</text>
</view>
```

**底部双按钮**：
```html
<view class="retry-actions">
  <button class="btn-secondary" bindtap="onCancel">取消</button>
  <button class="btn-primary" bindtap="onConfirm">确认</button>
</view>
```
对应的CSS：
```css
.retry-actions { display: flex; gap: 16rpx; margin-top: 16rpx; }
.retry-actions button { flex: 1; margin: 0; }
```

---

## 2. JS 规范

### 2.1 命名约定

| 类型 | 命名 | 例 |
|---|---|---|
| 页面变量 | 驼峰 | `loading`、`activeTab` |
| 事件处理函数 | on 前缀 | `onLogin`、`onTabChange` |
| 内部方法 | _ 前缀 | `_loadData`、`_authHeader` |
| HTTP 请求方法 | 驼峰动词 | `loadBrowse`、`submitRecording` |

### 2.2 网络请求模式

```js
// 标准模式
wx.request({
  url: app.globalData.apiBaseUrl + '/api/wx/...',
  method: 'POST',
  data: { ... },
  header: Object.assign(
    { 'Content-Type': 'application/json' },
    this._authHeader()
  ),
  success: (res) => {
    if (res.statusCode >= 200 && res.statusCode < 300) {
      // 业务逻辑
    } else {
      wx.showToast({ title: '失败 ' + res.statusCode, icon: 'none' });
    }
  },
  fail: () => wx.showToast({ title: '网络异常', icon: 'none' })
});
```

### 2.3 鉴权 Header

所有受保护接口必须带：

```js
_authHeader() {
  const token = wx.getStorageSync('ib_access_token');
  return token ? { 'Authorization': 'Bearer ' + token } : {};
}
```

### 2.4 上传文件（录音）

```js
wx.uploadFile({
  url: app.globalData.apiBaseUrl + '/api/wx/speak/practice/submit',
  filePath: this.data.audioPath,  // 本地临时路径
  name: 'audio',                    // 后端 Form name
  formData: { session_id, part, ... },
  header: this._authHeader(),
  success: (res) => {
    const body = typeof res.data === 'string' ? JSON.parse(res.data) : res.data;
    // 业务逻辑
  },
  fail: (err) => wx.showToast({ title: '上传失败', icon: 'none' })
});
```

### 2.5 页面跳转

| 跳转类型 | API | 何时用 |
|---|---|---|
| tabBar 页面 | `wx.switchTab` | 4 个 tab 之间切换 |
| 普通页面 | `wx.navigateTo` | 子页面（保留返回栈） |
| 重置 | `wx.reLaunch` | 登出后回登录页 |

**严禁**：用 `wx.switchTab` 跳非 tabBar 页面（静默失败）。

---

## 3. 后端 API 规范

### 3.1 路径前缀

| 端 | 前缀 |
|---|---|
| Web 端 | `/api/*` |
| 小程序 | `/api/wx/*` |

**禁止**：小程序调用 `/api/*`（数据契约不同）。

### 3.2 路由命名

```
POST /api/wx/<feature>/<action>
GET  /api/wx/<feature>/<resource>
GET  /api/wx/<feature>/<resource>/{id}
```

例：
- `POST /api/wx/study/vocab/random`
- `GET  /api/wx/study/review/due`
- `POST /api/wx/study/mistakes/{word}/mark-correct`

### 3.3 路由层原则（强制）

**路由文件**（`routers/wx_*.py`）只做：
1. 参数解析（Pydantic / Form / Query）
2. 调 service 层
3. 序列化响应（Pydantic response_model）

**禁止**：
- 业务逻辑写在路由
- 直接调 repository 跨过 service

### 3.4 service 层原则

**职责**：
1. 业务编排（多个 repository 调用）
2. 用户隔离校验（user_id 必传）
3. 事务管理（如果需要）

### 3.5 错误响应

```python
# 业务错误 → 400
raise HTTPException(status_code=400, detail="题库为空")

# 未授权 → 401（自动 by Depends）
# 数据格式错 → 422（自动 by Pydantic）
# 服务端错 → 500（自动 by FastAPI，但应该 log）
```

---

## 4. 数据库规范

### 4.1 表命名

| 类型 | 命名 | 例 |
|---|---|---|
| 业务表 | 复数或集合 | `learning_records`、`vocab_cache` |
| 用户表 | `web_user` | 唯一 |
| 关联表 | `<a>_<b>` | `speaking_practice_records` |

### 4.2 字段规范

| 字段 | 必带 | 类型 | 默认 |
|---|---|---|---|
| 主键 | ✅ | `INTEGER PRIMARY KEY AUTOINCREMENT` | - |
| 用户隔离 | ✅ | `user_id INTEGER NOT NULL` | - |
| 时间戳 | ✅ | `created_at TEXT NOT NULL`<br>`updated_at TEXT NOT NULL DEFAULT ''` | ISO8601 |
| 同步状态 | ✅ | `sync_status TEXT NOT NULL DEFAULT 'synced'` | 'synced' / 'pending_upload' |

### 4.3 唯一约束

**关键表必须有唯一约束**：
- `web_user.email` UNIQUE
- `web_user.openid` UNIQUE
- `speaking_practice_records.session_id` UNIQUE（保证重录可定位）

**upsert 模式**：任何"客户端可能重做"的资源必须有 upsert 接口（`create_or_update` 或先查后决定）。

### 4.4 索引

```sql
CREATE INDEX idx_<table>_<field>
    ON <table>(<field>);
```

最少索引：
- `learning_records(user_id, word)` UNIQUE
- `learning_records(user_id, next_review)`
- `mistakes(user_id, word)` UNIQUE
- `speaking_practice_records(user_id, created_at DESC)`

---

## 5. 鉴权规范

### 5.1 Token 存储

| 端 | 存储 |
|---|---|
| Web | HTTP-only cookie（`ie_session`） |
| 小程序 | `wx.setStorageSync('ib_access_token')` |

### 5.2 Token 类型

| Token | TTL | 用途 |
|---|---|---|
| access_token | 1 小时 | API 请求 |
| refresh_token | 30 天 | 刷新 access_token |

### 5.3 请求头

- Web：cookie 自动带
- 小程序：`Authorization: Bearer <access_token>`

### 5.4 失效处理

- 小程序暂未实现 refresh：access_token 过期 → 用户重新登录
- 后续：检测 401 → 调 `/api/wx/refresh` → 重发原请求

---

## 6. 真机调试规范

### 6.1 前置条件 checklist

- [ ] uvicorn `ielts_buddy.web.main:app`（不是 `app:app`）
- [ ] uvicorn `--host 0.0.0.0`（不是 127.0.0.1）
- [ ] `IELTS_BUDDY_LLM_API_KEY` shell export（不是仅 .env）
- [ ] `app.js` 的 `apiBaseUrl` = Mac LAN IP
- [ ] Mac 与手机同 WiFi（同网段）
- [ ] 微信开发者工具「不校验合法域名」已勾选
- [ ] pywhispercpp 模型已下载

### 6.2 推送代码到手机

微信开发者工具 → 真机调试 → 自动预览 → 扫码。
**修改代码后必须重新扫码**（IDE 推送到手机是按扫码时机）。

### 6.3 手机 vConsole

小程序右上角 ··· 菜单 → 打开 vConsole → 看 console.log 和网络请求。

---

## 7. 开发工作流规范

### 7.1 分支

- 主分支：`master`
- 暂未启用 feature branch（单人开发，单分支推进）

### 7.2 Commit 规范

格式：`<type>(<scope>): <subject>`

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | bug 修复 |
| `chore` | 杂项（依赖、配置） |
| `refactor` | 重构（无功能变化） |
| `docs` | 文档 |
| `test` | 测试 |

例：`fix(speak/practice): 重录场景支持（submit 检测已存在 record_id -> 复用并 update_audio）`

### 7.3 推送方式

```bash
# TRAE IDE 内（沙盒拦截时）
launchctl asuser $UID bash -c '
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
git add <files>
git commit -m "..."
git push origin master
'

# Mac Terminal 直接
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
git add <files>
git commit -m "..."
git push origin master
```

---

## 8. 错误处理规范

### 8.1 前端错误

| 场景 | 处理 |
|---|---|
| 网络异常 | `wx.showToast({ title: '网络异常', icon: 'none' })` |
| 业务失败 | `wx.showToast({ title: '失败原因', icon: 'none' })` |
| 响应解析失败 | `wx.showToast({ title: '响应解析失败', icon: 'none' })` |
| 录音失败 | `wx.showToast({ title: '录音失败：' + errMsg, icon: 'none' })` |
| 权限被拒 | 跳到手机系统设置 |

### 8.2 后端错误

| 场景 | HTTP | 处理 |
|---|---|---|
| 用户未登录 | 401 | 自动 by `Depends(get_current_user)` |
| 业务参数错 | 400 | `raise HTTPException(400, detail)` |
| 数据格式错 | 422 | 自动 by Pydantic |
| 资源不存在 | 404 | `raise HTTPException(404, detail)` |
| 服务端错 | 500 | 自动 + log |

### 8.3 LLM 失败降级

| 场景 | 降级 |
|---|---|
| `LLM_DRY_RUN=True` | mock 数据 |
| LLM 调用失败 | retry once → mock 数据 + `score_fallback=True` |
| Whisper 不可用 | 空 transcript + `whisper_fallback=True` |
| 录音为空 | LLM 看到 "(no speech detected)" → 给"请重新录制"建议 |

---

## 9. 代码组织规范

### 9.1 目录结构

```
src/ielts_buddy/
├── commands/          # CLI 子命令（web 端 CLI 用）
├── core/              # 核心 models / config
├── repositories/      # 数据访问层（SQLite + MySQL 双实现）
│   ├── sqlite_repo.py
│   ├── mysql_repo.py
│   └── fallback_repo.py   # 自动 fallback 包装
├── services/          # 业务逻辑层（Web / 小程序共享）
├── monitoring/        # 同步任务 / 通知
└── web/               # FastAPI 入口
    ├── auth/
    ├── routers/       # API 路由（含 wx_*.py）
    ├── templates/     # Jinja2 HTML 模板
    └── ...

miniprogram/
├── pages/             # 所有页面（auth/study/review/speak/me）
├── utils/             # 工具（request.js）
├── app.js             # 入口
└── app.json           # 路由 + tabBar
```

### 9.2 命名空间

- 路由前缀 `/api/wx/` — 小程序专属
- Service 类名 `<Feature>Service` — 业务类
- Repository 类名 `<DB><Feature>Repository` — 数据类（SQLite/MySQL）

---

## 10. 安全规范

### 10.1 输入校验

- 所有用户输入必须 Pydantic 校验（路由层）
- 文件上传必须有 mime + size 校验
- SQL 必须参数化（不准字符串拼接）

### 10.2 密码

- bcrypt 哈希（**不准明文**）
- `JWT_SECRET` 必须设置（dev 默认有警告，生产强随机）
- access_token 不存数据库（仅签发）

### 10.3 dev-mock-login

- **仅 dev 环境启用**（`IELTS_BUDDY_ENV != 'prod'`）
- 生产返回 403
- 真机调试必走 dev-mock-login

### 10.4 用户隔离

- 所有业务表带 `user_id`
- 音频文件按 user_id 分子目录
- 所有查询 `WHERE user_id = ?`

---

## 11. 性能规范

### 11.1 后端

- 同步 DB 操作走 `asyncio.to_thread`（避免阻塞 event loop）
- 长连接用 lifespan（启动期建 sync_worker）
- SQLite WAL 模式（读写并发）
- 索引必备（user_id + 时间）

### 11.2 小程序

- 列表用 `wx:for` + `wx:key`（避免重复渲染）
- 大列表用 `lazyCodeLoading`（按需加载）
- 图片用 `<image>` 不存 base64
- 数据预加载：`onShow` 而不是 `onLoad`（tabBar 复用时 onLoad 不再触发）

### 11.3 录音

- `wx.uploadFile` 而非 `wx.request`（音频必须 multipart）
- 单文件 ≤ 30MB
- 采样率 16kHz（避免转码）

---

## 12. 相关文档

- 设计文档：`docs/miniprogram/W10/01-小程序功能设计文档.md`
- 三端协同：`docs/miniprogram/W10/02-三端协同设计.md`
- 技术复盘：`docs/miniprogram/W10/03-技术复盘.md`
- 入口导航：`docs/miniprogram/W10/README.md`