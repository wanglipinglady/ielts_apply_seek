# 阶段 0：Web 骨架

## 目标
创建一个 FastAPI 应用骨架，能在 `python -m ielts_buddy.web.main` 下启动，并响应首页。本阶段不接入任何 Service，只搭壳子。

## 改动文件
- 新增 `src/ielts_buddy/web/__init__.py`
- 新增 `src/ielts_buddy/web/main.py`
- 新增 `src/ielts_buddy/web/config.py`
- 新增 `src/ielts_buddy/web/templates/base.html`
- 新增 `src/ielts_buddy/web/templates/pages/index.html`
- 新增 `src/ielts_buddy/web/static/css/app.css`
- 新增 `src/ielts_buddy/web/static/js/htmx.min.js`（vendored，1.9.10）
- 新增 `tests/test_web/__init__.py`
- 新增 `tests/test_web/test_app_boot.py`
- 修改 `requirements.txt`（追加 fastapi/uvicorn/jinja2/python-multipart）
- 修改 `pyproject.toml`（同步依赖；不增 fastapi 为必需依赖，用 [web] extra 装）

## 设计要点

### main.py
```python
def create_app() -> FastAPI:
    app = FastAPI(title="IELTS Buddy Web", version="0.1.0")
    # 1. 挂载 static
    # 2. 配置 Jinja2Templates
    # 3. 注册首页路由
    # 4. 注册健康检查 /healthz
    return app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ielts_buddy.web.main:app", host="127.0.0.1", port=8000, reload=True)
```

### 依赖隔离策略
- `pyproject.toml` 把 fastapi/uvicorn/jinja2/python-multipart 放入 `[project.optional-dependencies] web = [...]`
- CLI 命令 `ib` 不依赖 web 包；web 包反过来也不依赖 click
- `src/ielts_buddy/web/__init__.py` 只在 web 进程里被 import

### 模板目录
```
src/ielts_buddy/web/templates/
├── base.html          # 公共骨架（含 HTMX 引入、导航、用户态占位）
└── pages/
    └── index.html     # 阶段0 占位：显示 "Web MVP Coming"
```

## 自动化验收

`tests/test_web/test_app_boot.py`：
- `test_app_starts()`：构造 app，不抛异常
- `test_index_page_returns_200()`：TestClient GET / 返回 200，HTML 含 "IELTS"
- `test_healthz()`：GET /healthz 返回 `{"status": "ok"}`
- `test_static_css_served()`：GET /static/css/app.css 返回 200 + css content-type
- `test_htmx_loaded()`：GET /static/js/htmx.min.js 返回 200

## 人工验收

```bash
cd /Users/wangliping/Public/selfProgram/ielts_apply_seek
pip install -e ".[web]"      # 装 FastAPI 等
PYTHONPATH=src python -m ielts_buddy.web.main --port 8000
# 浏览器打开 http://127.0.0.1:8000/
# 看到 "Web MVP Coming" + 一个 htmx-loaded 标记
# DevTools Network 看 htmx.min.js 200 OK
```

## 风险点
- HTMX 必须 vendored 离线可用（不能走 CDN，服务器可能没外网）
- reload=True 仅 dev 用，生产用 gunicorn / uvicorn 直接起

## 收尾标准
- [ ] 所有自动化用例通过
- [ ] 浏览器实际验证
- [ ] docs/web-mvp/records/2026-07-25-01-skeleton.md 写好
- [ ] docs/web-mvp/retros/ 无未解决问题
