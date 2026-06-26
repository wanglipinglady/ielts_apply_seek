#!/usr/bin/env python3
"""
grok.py - LLM API 代理

用法: python grok.py "用户问题" -s "系统提示" --json

这是一个通用的 LLM 调用脚本，用于项目中的 AI 作文批改功能。

支持的 API:
- OpenAI (GPT-4, GPT-3.5)
- SiliconFlow (国内推荐, 支持 Qwen/Llama)
- Anthropic Claude
- 其他 OpenAI 兼容格式的 API
"""

import sys
import json
import argparse
from pathlib import Path


def load_api_key():
    """从配置文件加载 API Key
    
    配置文件位置: 项目目录 docs/grok_config.json
    格式: {"provider": "openai", "api_key": "sk-xxx", "model": "MiniMax-M2.7-highspeed", "base_url": "https://api.minimaxi.com/v1"}
    """
    # 项目目录下的配置文件
    config_path = Path(__file__).parent / "grok_config.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def call_openai(prompt: str, system: str, model: str, api_key: str, base_url: str = None, timeout: int = 60) -> str:
    """调用 OpenAI 兼容 API"""
    from openai import OpenAI
    
    kwargs = {"api_key": api_key, "timeout": timeout}
    if base_url:
        kwargs["base_url"] = base_url
    
    client = OpenAI(**kwargs)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        timeout=timeout
    )
    
    return response.choices[0].message.content


def call_anthropic(prompt: str, system: str, model: str, api_key: str) -> str:
    """调用 Anthropic Claude API"""
    import anthropic
    
    client = anthropic.Anthropic(api_key=api_key)
    
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.content[0].text


def main():
    parser = argparse.ArgumentParser(
        description="LLM API 代理 - 用于 AI 作文批改",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python grok.py "你的作文内容" -s "系统提示" --json
  
配置文件 (~/.ielts-buddy/grok_config.json):
  {
    "provider": "siliconflow",
    "api_key": "sk-your-key",
    "model": "Qwen/Qwen2.5-7B-Instruct"
  }
        """
    )
    parser.add_argument('prompt', help='用户问题/作文内容（如果为空，则从 stdin 读取）')
    parser.add_argument('-s', '--system', default='You are a helpful assistant.', 
                        help='系统提示')
    parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    parser.add_argument('--provider', default='openai',
                        choices=['openai', 'siliconflow', 'anthropic'],
                        help='API 提供商')
    parser.add_argument('--model', default='MiniMax-M2.7-highspeed',
                        help='模型名称')
    parser.add_argument('--api-key', help='API Key (也可在配置文件中设置)')
    parser.add_argument('--base-url', help='API Base URL (用于代理)')
    
    args = parser.parse_args()
    
    # 如果 prompt 为空或为 '-'，则从 stdin 读取
    if not args.prompt or args.prompt == '-':
        args.prompt = sys.stdin.read()
    
    # 加载配置
    config = load_api_key()
    
    # 确定 API 参数
    provider = args.provider
    api_key = args.api_key
    model = args.model
    base_url = args.base_url
    
    if config:
        provider = config.get('provider', provider)
        api_key = api_key or config.get('api_key')
        model = config.get('model', model)
        base_url = base_url or config.get('base_url')
    
    if not api_key:
        error_msg = "API Key 未设置。请在 docs/grok_config.json 中配置。"
        if args.json:
            print(json.dumps({"error": error_msg}))
        else:
            print(f"错误: {error_msg}", file=sys.stderr)
        sys.exit(1)
    
    # 调用 API
    try:
        print(f"DEBUG: provider={provider}, model={model}, base_url={base_url}", file=sys.stderr)
        if provider in ['openai', 'siliconflow']:
            content = call_openai(args.prompt, args.system, model, api_key, base_url)
        elif provider == 'anthropic':
            content = call_anthropic(args.prompt, args.system, model, api_key)
        else:
            raise ValueError(f"不支持的 provider: {provider}")
        
        if args.json:
            print(json.dumps({"content": content}))
        else:
            print(content)
            
    except Exception as e:
        error_msg = str(e)
        print(f"API 调用错误: {error_msg}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": error_msg}))
        sys.exit(1)


if __name__ == "__main__":
    main()
