# IELTS Apply Seek · 项目文档索引

> 同步于 v3.8（2026-08-23）。4 份核心文档都已根据最新代码核对。

## 1. 操作手册（用户侧）

| 文档 | 受众 | 主要内容 |
|---|---|---|
| [CLI 操作手册 (HTML)](./cli-manual/cli-manual.html) · [Markdown](./cli-manual/cli-manual.md) | 终端用户 / 自部署者 | 17 命令组 × 65 子命令的场景 / 边界 / 步骤；数据模式切换；错误排查；daemon + cron |
| [Web 操作手册 (HTML)](./web-manual/web-manual.html) · [Markdown](./web-manual/web-manual.md) | 浏览器用户 / 自部署者 | 28 个页面的场景 / 边界 / 步骤；鉴权与同步；环境变量清单 |

> **HTML** 版本含 echarts + mermaid 交互图表、自定义 CSS（封面/排版/暗色主题），适合浏览器查看。
> **Markdown** 版本保留全部文字与代码块，可直接在 VS Code / Typora / Obsidian 等编辑器中打开、搜索、复制。

## 2. 项目资料（团队侧）

| 文档 | 受众 | 主要内容 |
|---|---|---|
| [项目地图（对内）](../project-maps/project-map/project-map.html) | 接手开发者 / 架构师 | 三层架构 / 26 个系统清单 / 数据流 / 模块依赖 / DB schema / v3 Sync / 版本路线图 / Git 历史 / 风险 |
| [产品画布（对外）](../project-maps/product-canvas/product-canvas.html) | 候选用户 / 合作伙伴 / 决策者 | 价值主张 / 9 块画布 / 用户画像 / KPI / 功能矩阵 / 5 个典型场景 / 商业模式 / 路线图 / 竞品对比 / 风险 |

## 3. 交叉引用

- CLI 手册 §三 数据模式 ↔ Web 手册 §三 数据模式：同一套模式，三种 `*_DB_MODE` 环境变量
- 项目地图 §六 数据库 Schema ↔ CLI / Web 手册中所有"写入"步骤
- 项目地图 §十 风险与遗留 ↔ Web 手册 §二十三 错误排查（已修复的 5 个 bug 在两边都提到）
- 产品画布 §六 典型使用场景 ↔ CLI / Web 手册对应章节

## 4. 维护约定

- 任何新版本（v3.9+）发布前，更新 4 份文档的"版本"行与新增章节。
- 新增 CLI 子命令 / Web 页面：先在对应手册添加"场景 / 功能范围 / 边界 / 步骤"四段。
- 新增 v3.x 数据表：在项目地图 §六 与两份手册 §数据模式同步更新。
- 新增商业阶段：在产品画布 §七 / §八 / §九 同步更新。

## 5. 目录结构

```
docs/
├── README.md                       # 本文件
├── manuals/                        # 操作手册（用户侧）
│   ├── cli-manual/
│   │   ├── cli-manual.html         # 浏览器版（图表+暗色主题）
│   │   ├── cli-manual.md           # 编辑器版（VS Code / Typora 友好）
│   │   ├── assets/
│   │   └── _shared/
│   └── web-manual/
│       ├── web-manual.html
│       ├── web-manual.md
│       ├── assets/
│       └── _shared/
├── project-maps/                   # 项目资料（团队侧）
│   ├── project-map/
│   │   ├── project-map.html
│   │   ├── assets/
│   │   └── _shared/
│   └── product-canvas/
│       ├── product-canvas.html
│       ├── assets/
│       └── _shared/
├── PLAN.md                         # 既有项目级方案（不动）
├── PRD.md                          # 既有产品需求文档（不动）
├── online_local_技术详解.md         # 既有 online/local 模式详解（不动）
├── v3_mysql_fallback_design.md     # 既有 v3 设计稿（不动）
├── v3_retrospective.md             # 既有 v3 复盘（不动）
├── web-mvp/                        # 既有 Web MVP 阶段方案（不动）
├── brainstorm-v1.3.md              # 既有头脑风暴记录（不动）
└── 迭代版本归档.md                   # 既有版本归档（不动）
```

## 6. 后续待办（v3.9）

- [x] 把 `.nexus-map/` 用 nexus-mapper 重跑，更新到 v3.8。（已于 2026-08-23 完成）
- [x] 在 README.md 顶部加入本索引链接。
- [x] 为 CLI / Web 手册生成 Markdown 版本便于编辑器内查看。（已于 2026-08-24 完成）
- [ ] 给 `web/tools/regen_secrets.py` 与 `reset_password.py` 写专门操作手册。
- [ ] 把项目地图与产品画布翻译成英文版（候选海外用户 / 国际合作伙伴用）。