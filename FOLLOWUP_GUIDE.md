# IELTS Apply Seek Web 后续工作指南

## 一、实现与PRD差异分析

### 1.1 已完成功能（对照PRD）

| PRD章节 | 功能点 | 实现状态 | 说明 |
|---------|--------|----------|------|
| Phase 2 | 词汇测验 | ✅ 完成 | 页面+API |
| Phase 2 | 词库浏览 | ✅ 完成 | 搜索+筛选+分页 |
| Phase 3 | 个人词库CRUD | ✅ 完成 | 增删改查 |
| Phase 3 | 单词分类 | ✅ 完成 | 分类管理 |
| Phase 3 | 导入导出 | ✅ 完成 | CSV格式 |
| Phase 4 | 模拟考试 | ✅ 完成 | 计时+评分 |
| Phase 4 | AI批改 | ✅ 完成 | Mock实现 |
| Phase 4 | 学习计划 | ✅ 完成 | 目标+任务量 |
| Phase 4 | 报告生成 | ✅ 完成 | 周报+月报 |

### 1.2 PRD中未完全实现的功能

| 功能点 | PRD描述 | 当前状态 | 差距说明 |
|--------|---------|----------|----------|
| AI批改真实LLM | 调用GPT-4o进行真实批改 | Mock模拟 | 需要接入LLM API |
| PDF报告导出 | 生成可下载PDF报告 | HTML页面 | 需要PDF生成库 |
| 实时答题WebSocket | 多人实时答题对战 | 单人模式 | 需要WebSocket支持 |
| 移动端适配 | 响应式布局优化 | 基础适配 | UI细节待优化 |
| 数据永久化 | MySQL数据持久化 | SQLite演示 | 需要配置MySQL |

### 1.3 PRD缺失但建议添加的功能

| 功能点 | 建议 | 优先级 |
|--------|------|--------|
| 成就系统 | 学习徽章和里程碑 | 低 |
| 社区分享 | 分享学习成果 | 低 |
| 多语言支持 | 中英双语 | 低 |
| 暗色模式 | 深色主题切换 | 中 |

---

## 二、待处理任务清单

### 2.1 高优先级

| 任务 | 描述 | 预计工时 | 依赖 |
|------|------|----------|------|
| 修复测试失败 | 修复42个失败测试 | 4h | 无 |
| MySQL集成 | 配置MySQL连接 | 2h | MySQL服务 |
| LLM集成 | 接入真实AI批改 | 8h | API Key |

### 2.2 中优先级

| 任务 | 描述 | 预计工时 | 依赖 |
|------|------|----------|------|
| PDF导出 | 实现报告PDF下载 | 4h | pdfkit/weasyprint |
| 用户体验优化 | 加载状态和错误提示 | 4h | 无 |
| 移动端适配 | 响应式布局优化 | 6h | CSS框架 |

### 2.3 低优先级

| 任务 | 描述 | 预计工时 | 依赖 |
|------|------|----------|------|
| 成就系统 | 学习徽章 | 8h | 无 |
| 社区功能 | 分享和评论 | 16h | 用户系统 |
| WebSocket对战 | 实时多人答题 | 12h | WebSocket |

---

## 三、技术债务清理计划

### 3.1 立即处理（1周内）

```
1. 修复评分服务Pydantic验证错误
   - 文件: test_services/test_grading_service.py
   - 问题: score字段验证要求 >= 1
   - 方案: 调整mock数据或修改验证规则

2. 修复导入导出测试
   - 文件: test_services/test_sync_service.py
   - 问题: 记录持久化问题
   - 方案: 检查Repository实现

3. 修复MySQL连接测试
   - 文件: test_services/test_mysql_*.py
   - 问题: 缺少MySQL服务
   - 方案: 添加skip条件或使用Docker
```

### 3.2 短期处理（1-4周）

```
1. 接入真实LLM API
   - 添加 OpenAI/Anthropic API 调用
   - 实现重试和降级逻辑
   - 添加API Key配置管理

2. PDF报告生成
   - 选择 PDF 库 (pdfkit/weasyprint)
   - 设计报告模板
   - 实现异步生成和下载
```

### 3.3 中期处理（1-3月）

```
1. WebSocket实时功能
   - 搭建WebSocket服务
   - 实现实时答题
   - 添加房间管理

2. 移动端优化
   - 使用Tailwind CSS
   - 添加手势交互
   - 优化加载性能
```

---

## 四、代码质量改进建议

### 4.1 测试覆盖率目标

| 模块 | 当前覆盖率 | 目标 | 差距 |
|------|------------|------|------|
| routers | ~80% | 90% | +10% |
| services | ~70% | 85% | +15% |
| repositories | ~60% | 80% | +20% |

### 4.2 代码规范检查

```bash
# 运行代码检查
black --check src/
ruff check src/
mypy src/

# 修复问题
black src/
ruff check --fix src/
mypy src/ || true
```

### 4.3 性能优化建议

| 位置 | 问题 | 优化方案 |
|------|------|----------|
| 词库搜索 | 全量加载 | 添加分页和索引 |
| 报告生成 | 同步生成 | 改为异步任务 |
| 页面加载 | 多个API请求 | 合并为批量API |

---

## 五、部署指南

### 5.1 环境要求

- Python 3.10+
- Node.js 18+ (可选，用于静态资源)
- MySQL 8.0+ (生产环境)
- Redis 6+ (可选，用于缓存和WebSocket)

### 5.2 生产部署检查清单

- [ ] 设置环境变量 `IELTS_MODE=production`
- [ ] 配置MySQL连接字符串
- [ ] 配置LLM API Key
- [ ] 设置会话密钥 `SECRET_KEY`
- [ ] 配置HTTPS证书
- [ ] 设置日志级别和输出
- [ ] 配置备份策略
- [ ] 设置监控告警

### 5.3 Docker部署

```dockerfile
# Dockerfile (示例)
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "ielts_buddy", "web"]
```

---

## 六、知识库

### 6.1 项目架构

```
ielts_apply_seek/
├── src/ielts_buddy/
│   ├── web/                 # Web应用
│   │   ├── routers/         # 路由处理
│   │   ├── templates/      # Jinja2模板
│   │   ├── static/         # 静态资源
│   │   └── main.py         # 应用入口
│   ├── core/               # 核心模块
│   ├── services/           # 业务服务
│   └── repositories/       # 数据访问
├── tests/                  # 测试
├── docs/                   # 文档
└── scripts/                # 脚本
```

### 6.2 关键技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| Web框架 | FastAPI | 0.100+ |
| 模板引擎 | Jinja2 | 3.1+ |
| ORM | SQLAlchemy | 2.0+ |
| 数据库 | SQLite/MySQL | - |
| 测试 | pytest | 9.0+ |
| 前端 | 原生JS + CSS | - |

### 6.3 常见问题FAQ

**Q: 如何添加新的Web页面?**
A: 在 `routers/` 创建路由文件，在 `templates/pages/` 创建HTML模板，在 `main.py` 注册路由。

**Q: 如何添加新的API端点?**
A: 在路由文件中使用 `@api_router` 装饰器，返回JSON响应。

**Q: 如何处理用户认证?**
A: 使用 `Depends(get_current_user)` 获取当前用户，使用 `WebUser` 模型。

**Q: 如何添加数据库表?**
A: 在 `repositories/` 创建Repository类，使用SQLAlchemy定义模型。

---

## 七、版本记录

| 版本 | 日期 | 修改内容 | 作者 |
|------|------|----------|------|
| V1.0 | 2026-07-27 | 初始实现，包含Phase 2-4功能 | TRAE AI |

---

**最后更新**: 2026-07-27
**下次评审**: 2026-08-10
