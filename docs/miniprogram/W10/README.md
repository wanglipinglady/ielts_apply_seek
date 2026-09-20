# 智取屠鸭山 - W10 文档地图

> **入口**：本目录是微信小程序从开发到真机调试全流程的文档沉淀。
> **适用范围**：新对话开窗 / 新开发者加入 / 下个迭代规划 时查阅。

---

## 🚦 当前状态（2026-09-21）

| 项 | 状态 |
|---|---|
| 小程序功能（4 tab + 登录） | ✅ 已完成 |
| 后端 API（`/api/wx/*`） | ✅ 已完成 |
| 真机调试链路 | ✅ 已通（whisper + LLM + LAN IP） |
| 端到端测试 | ✅ 已验证 |
| 文档沉淀 | ✅ 本目录 |
| 真实发布上线 | ❌ 暂未 |

---

## 📑 文档导航

按"先读哪个"排序：

### 1️⃣ 必读（任何场景）

- **[01-小程序功能设计文档.md](./01-小程序功能设计文档.md)**
  - 功能总览 + 详细设计 + 用户场景
  - 4 tab 一一对应 Web 端功能
  - 设计原则（不重复代码 / 路径隔离 / 内联 vs 独立）

### 2️⃣ 重要（理解跨端）

- **[02-三端协同设计.md](./02-三端协同设计.md)**
  - 本地 SQLite / Web / 小程序 三端共用一个 DB
  - 三种登录流程对照
  - 用户隔离 + 数据同步
  - 部署拓扑

### 3️⃣ 重要（避坑）

- **[03-技术复盘.md](./03-技术复盘.md)**
  - 15 个关键问题的定位过程
  - 每个问题的根因 + 技术选型 + 决策路径
  - 真机调试 checklist
  - WXML 关键字扫描清单

### 4️⃣ 规范（开发约束）

- **[04-Spec沉淀.md](./04-Spec沉淀.md)**
  - WXML / WXSS / JS 规范
  - 后端 API 规范
  - 数据库 / 鉴权 / 安全规范
  - 性能规范

### 5️⃣ 下次迭代规划

- **[05-下一轮迭代规划.md](./05-下一轮迭代规划.md)**（如果存在）
  - TODO / 待优化项 / 未来方向

---

## 🔍 快速索引（按场景）

| 你要做的 | 读哪份 |
|---|---|
| 了解小程序有哪些功能 | 01 |
| 理解为什么这么设计 | 01 第 4-5 节 + 02 |
| 加一个新页面 | 04 第 1-2 节（WXML/JS 规范） |
| 加一个新 API | 04 第 3 节（API 规范） |
| 调试真机 | 03 第 6 节（checklist）+ 01 第 6 节（配置） |
| 修一个 bug | 03 第 2 节（已有问题 + 解决方案） |
| 推送代码到 GitHub | 04 第 7 节 + 03 第 2.12 节（沙盒） |
| 部署到生产 | 02 第 9 节（部署拓扑） |

---

## 📁 项目地图（高层）

```
智取屠鸭山 (ielts_apply_seek/)
│
├── miniprogram/                  ← 微信小程序
│   ├── app.js / app.json
│   ├── pages/
│   │   ├── auth/login/           ← 登录
│   │   ├── study/                ← 学习（学）
│   │   ├── review/               ← 复习
│   │   ├── speak/                ← 口语
│   │   └── me/                   ← 我
│   └── utils/
│
├── src/ielts_buddy/              ← 后端 Python
│   ├── commands/                 ← CLI
│   ├── repositories/             ← 数据层（SQLite + MySQL）
│   ├── services/                 ← 业务层（Web + 小程序共享）
│   ├── web/
│   │   ├── routers/              ← API 路由（含 wx_*.py）
│   │   ├── templates/            ← Web HTML
│   │   ├── auth/                 ← JWT / 鉴权
│   │   ├── speaking_grade_service.py
│   │   ├── whisper_service.py
│   │   ├── llm_service.py
│   │   └── main.py               ← FastAPI 入口
│   └── core/
│
├── docs/
│   ├── miniprogram/
│   │   ├── W1/ ... W8/           ← 历史 sprint 文档
│   │   ├── W9/                   ← 提报材料
│   │   └── W10/                  ← 本目录（当前）
│   ├── web-mvp/                  ← Web 端文档
│   └── ...
│
├── scripts/
│   ├── auto/                     ← 自动脚本（含 08-auto_git_push.sh）
│   └── ...
│
└── tests/
```

---

## 🔧 关键技术决策（速查）

| 决策 | 选择 | 详见 |
|---|---|---|
| 录音 API | wx.getRecorderManager | 03 #4 |
| 录音参数 | mp3 + 16kHz | 01 #3.4 |
| 登录 mockCode | 固定 dev_test_user001 | 03 #2.9 |
| Random 学习位置 | 内联到 study/index | 01 #3.2.2 |
| 后端 ASGI 入口 | ielts_buddy.web.main:app | 03 #2.3 |
| LLM API 读取时机 | uvicorn 启动时（重启生效） | 03 #2.5 |
| Whisper 模型下载 | hf-mirror.com + 手动放 search_dir | 03 #2.2 |
| TRAE 沙盒 git | launchctl asuser $UID | 03 #2.12 |
| me/index 功能 | 只保留考试日历 | 01 #3.5 + 03 #2.10 |
| 录音按钮 bindtap | startRecord（不是 startPractice） | 03 #2.4 |

---

## 🚀 启动开发环境（速查）

```bash
# 1. 启动后端（Mac Terminal，必须）
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
export IELTS_BUDDY_LLM_API_KEY="sk-cp-..."  # 不能为空
export IELTS_BUDDY_LLM_BASE_URL="https://api.minimaxi.com/v1"
export IELTS_BUDDY_LLM_MODEL="MiniMax-M2.7-highspeed"
PYTHONPATH=src uvicorn ielts_buddy.web.main:app --host 0.0.0.0 --port 8000

# 2. 微信开发者工具
#    - 打开 miniprogram/
#    - 真机调试 → 自动预览 → 扫码

# 3. 浏览器（Web 端）
open http://127.0.0.1:8000
```

---

## 📞 关键联系人 / 文件

| 角色 | 文件 / 路径 |
|---|---|
| 后端 FastAPI 入口 | `src/ielts_buddy/web/main.py` |
| 小程序入口 | `miniprogram/app.js` |
| 小程序路由配置 | `miniprogram/app.json` |
| LLM 服务 | `src/ielts_buddy/web/llm_service.py` |
| Whisper 服务 | `src/ielts_buddy/web/whisper_service.py` |
| 口语评分 | `src/ielts_buddy/web/speaking_grade_service.py` |
| 小程序登录路由 | `src/ielts_buddy/web/routers/wechat.py` |
| 小程序学习路由 | `src/ielts_buddy/web/routers/wx_study.py` |
| 小程序口语路由 | `src/ielts_buddy/web/routers/wx_speak.py` |
| 数据库 schema | `src/ielts_buddy/repositories/sqlite_repo.py:264` |
| 推送脚本 | `scripts/auto/08-auto_git_push.sh` |

---

## 📅 文档版本

| 版本 | 日期 | 变更 |
|---|---|---|
| v3.9 | 2026-09-21 | 首次完整沉淀（4 tab + 11 个 WXML 坑 + 15 个技术问题） |

---

## 🔗 外部资源

- [微信小程序官方文档](https://developers.weixin.qq.com/miniprogram/dev/framework/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [whisper.cpp 项目](https://github.com/ggerganov/whisper.cpp)
- [pywhispercpp Python binding](https://github.com/abdeladim-s/pywhispercpp)
- [MiniMax LLM API](https://api.minimaxi.com/)

---

## 下一步

读完本目录后，建议：

1. **新对话开窗** → 直接说"我已读 W10 文档，要做 X 任务"
2. **新开发者** → 依次读 01 → 02 → 03 → 04，每份约 10 分钟
3. **真机调试** → 按 03 第 6 节 checklist 走一遍
4. **修 bug** → 先查 03 第 2 节类似问题，再决定方案