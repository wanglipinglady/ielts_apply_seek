"""
tests/test_contracts/
契约测试目录——锁住"多端共享 API 的响应 / 入参结构"。

为什么需要契约测试：
- CLI / Web / 微信小程序 三端共享同一份 FastAPI 后端
- 改了一个字段，三端同时受影响
- 契约测试 = schema 守门员：CI 失败 = 改动破坏了老调用方

使用姿势：
    pytest tests/test_contracts/ -v

新增契约测试时：
1. 复制下面的样板
2. 改 endpoint / 字段名
3. 跑一遍确认通过
4. 提交

注意：
- 这些测试**不验证业务逻辑**——只验证"返回结构 / 必填字段"
- 业务逻辑测试在 tests/test_web/ 和 tests/test_services/ 已有
"""