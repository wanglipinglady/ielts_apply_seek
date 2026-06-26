# Grok.py 配置指南

## 概述

`grok.py` 是 AI 作文批改功能的 LLM API 代理脚本。

## 快速配置

### 1. 创建配置文件

在 `~/.ielts-buddy/` 目录下创建 `grok_config.json`：

```bash
# Windows
mkdir %USERPROFILE%\.ielts-buddy
# 复制 docs/GROK_CONFIG_EXAMPLE.json 并重命名为 grok_config.json
```

### 2. 获取 API Key

#### 推荐：硅基流动（国内可用）
1. 访问 https://cloud.siliconflow.cn
2. 注册并登录
3. 进入「API 密钥」页面
4. 创建新密钥，复制 key

#### 备选：OpenAI
1. 访问 https://platform.openai.com
2. 注册并登录
3. 进入「API Keys」页面
4. 创建新密钥

### 3. 修改配置

编辑 `~/.ielts-buddy/grok_config.json`：

```json
{
    "provider": "siliconflow",
    "api_key": "sk-your-actual-api-key",
    "model": "Qwen/Qwen2.5-7B-Instruct"
}
```

### 4. 测试

```bash
cd docs
python grok.py "Hello, how are you?" --json
```

## 支持的提供商

| 提供商 | provider 值 | 模型示例 | 说明 |
|--------|-------------|---------|------|
| 硅基流动 | `siliconflow` | Qwen/Llama | 国内推荐，按量计费 |
| OpenAI | `openai` | gpt-4, gpt-3.5 | 国际服务 |
| Anthropic | `anthropic` | claude-3-sonnet | Claude 系列 |

## 常见问题

### Q: 报错 "API Key 未设置"
A: 确保 `grok_config.json` 文件存在且 `api_key` 正确

### Q: 报错 "Connection timeout"
A: 检查网络连接，或增加 grok.py 中的 timeout 参数

### Q: 使用 OpenAI 报错
A: OpenAI 在国内可能需要代理，设置 `base_url` 为代理地址

## 费用说明

- **硅基流动**：按 token 计费，价格便宜
- **OpenAI**：按 API 调用计费，GPT-4 较贵
- **建议**：先用低价模型测试，确认功能正常后再切换
