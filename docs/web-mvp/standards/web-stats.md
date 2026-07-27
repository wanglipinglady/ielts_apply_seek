# Web 端统计页面规范

> 适用：`/dashboard` `/stats` 两个页面 + `/api/stats/*` API。
> 阶段 2 落地后形成的约定。

## 1. URL

| 路径 | 方法 | 鉴权 | 用途 |
|---|---|---|---|
| `/dashboard` | GET | access | 欢迎语 + 4 张摘要卡 + 跳转入口 |
| `/stats` | GET | access | 完整统计（摘要 + 等级 + Band + 趋势） |
| `/api/stats/summary` | GET | access | Dashboard 摘要 JSON |
| `/api/stats/overview` | GET | access | Stats 全量 JSON |

未登录访问页面 → 302 → /login
未登录调 API → 401

## 2. 数据装配

### 2.1 `WebStatsService`（Web 端自研）

不依赖 CLI 的 `services/stats_service.py`，原因见
[`docs/web-mvp/retros/2026-07-25-phase1-jwt.md`](../retros/2026-07-25-phase1-jwt.md) §3
+ `standards/web-architecture.md` §3.3。

业务方法（与 CLI `StatsService` 对齐）：

| 方法 | 返回 | 说明 |
|---|---|---|
| `total_stats()` | `dict` | 累计：词数 / 复习次数 / 正确 / 错误 / 正确率 / 已掌握 |
| `today_stats()` | `dict` | 今日新学 / 复习 / 正确 / 错误 / 正确率 |
| `level_distribution()` | `dict[int, int]` | 记忆等级 0-6 → 词数 |
| `due_count()` | `int` | 待复习数（next_review <= today） |
| `get_streak()` | `tuple[int, int]` | 当前 / 最长连续天数 |
| `get_band_progress()` | `list[tuple]` | (band, total, mastered, ratio) |
| `get_daily_trend(days)` | `list[tuple]` | (date, studied, accuracy) |

### 2.2 响应 Pydantic 模型（`web/stats_schemas.py`）

- `StatsSummary`：5 个核心数字（dashboard 卡片用）
- `LevelDistributionItem(level, count)`：等级分布
- `BandProgressItem(band, total, mastered, ratio)`：Band 进度
- `DailyTrendItem(date, studied)`：每日趋势
- `StatsOverview(summary, level_distribution, band_progress, trend)`：全量聚合

**约定**：Web 端 API 响应**必须**走 Pydantic 模型，禁止裸 dict。

## 3. 模板约定

### 3.1 `_summary_cards.html`

Dashboard 摘要卡 partial，被两个地方复用：
1. `/dashboard` 整页直接 `{% include %}`
2. 后续如果要做"自动刷新"，HTMX `hx-get="/api/stats/summary"` + `hx-target="#dashboard-cards"` + `hx-swap="innerHTML"`

### 3.2 `stats.html`

四段表格：
- 摘要（8 张卡）
- 记忆等级分布（柱状条）
- 各 Band 掌握进度（带比例）
- 最近 7 天趋势

**不用图表库**：MVP 阶段用纯 CSS `<div class="bar">` 进度条，宽度按百分比。
**i18n 留白**：所有文案中文硬编码，待 T-07 抽 babel。

## 4. 测试覆盖（`test_stats_api.py`）

| 场景 | 期望 |
|---|---|
| 未登录调 `/api/stats/summary` | 401 |
| 未登录访问 `/stats` | 302 → /login |
| 无数据 | summary 全 0、level_distribution 7 条空、band 5 个空、trend 7 条空 |
| 有数据 | summary 数字准确、level_distribution 按 level 聚合、band 比例 ≤ 1.0 |
| 多用户隔离 | A 答 10 题 → B 看到全 0 |
| Dashboard 渲染 | 200 + 含"欢迎" + 4 张卡 |
| Stats 渲染 | 200 + 含"摘要" + "等级分布" + "Band" + "7 天" |

## 5. 已知限制（MVP 范围）

- 趋势只有 7 天（CLI `StatsService` 有 30 天切换，Web 暂不暴露）
- 没有"答错率最高 N 个词"列表（在 CLI `ib stats show` 有；Web 暂无入口）
- 没有"按 band 筛选"维度（T-08 自适应难度时一起做）

## 6. 后续优化建议

1. **HTMX 自动刷新**：dashboard 每 30s 自动拉一次 `summary`，无需刷新整页
2. **导出 CSV**：`/api/stats/export?format=csv`（CLI `sync_service` 已有逻辑，Web 加个下载入口）
3. **趋势图换图表库**：7 天以上用 ECharts 折线，7 天内仍用表格
4. **难度自适应联动**：根据正确率动态调整 band 分布（T-08）
