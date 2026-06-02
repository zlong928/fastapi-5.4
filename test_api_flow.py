#!/usr/bin/env python3
"""测试 API 调用流程"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
from app.core.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

# Load environment
load_dotenv()

print("=" * 60)
print("API 配置检查")
print("=" * 60)
print(f"OPENAI_API_KEY: {OPENAI_API_KEY[:20]}..." if OPENAI_API_KEY else "未配置")
print(f"OPENAI_BASE_URL: {OPENAI_BASE_URL}")
print(f"OPENAI_MODEL: {OPENAI_MODEL}")
print()

# Test API connection
import httpx
import json

def test_api_call():
    print("=" * 60)
    print("测试 API 调用")
    print("=" * 60)

    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    if not url.endswith("/chat/completions"):
        if "/v1" not in url:
            url = f"{OPENAI_BASE_URL.rstrip('/')}/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": "Say OK"}],
        "stream": True,
        "max_tokens": 10
    }

    print(f"请求 URL: {url}")
    print(f"模型: {OPENAI_MODEL}")
    print()

    try:
        with httpx.stream("POST", url, headers=headers, json=body, timeout=30.0) as response:
            print(f"HTTP 状态码: {response.status_code}")

            if response.status_code != 200:
                error_text = response.read().decode("utf-8")
                print(f"错误响应: {error_text}")
                try:
                    error_json = json.loads(error_text)
                    if "error" in error_json:
                        error_info = error_json["error"]
                        if isinstance(error_info, dict):
                            print(f"✗ 错误类型: {error_info.get('type')}")
                            print(f"✗ 错误信息: {error_info.get('message')}")
                        else:
                            print(f"✗ 错误: {error_info}")
                except json.JSONDecodeError:
                    print(f"✗ 无法解析错误响应")
                return False

            print("✓ 连接成功，开始接收流式响应...")
            print()

            tokens = []
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()
                if line == "[DONE]":
                    break

                try:
                    payload = json.loads(line)
                    if "error" in payload:
                        print(f"✗ 流式响应中的错误: {payload['error']}")
                        return False

                    choice = (payload.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    token = delta.get("content")
                    if token:
                        tokens.append(token)
                        print(f"接收到 token: {token}")
                except json.JSONDecodeError:
                    continue

            if tokens:
                print()
                print(f"✓ 成功接收 {len(tokens)} 个 tokens")
                print(f"完整响应: {''.join(tokens)}")
                return True
            else:
                print("✗ 未接收到任何 token")
                return False

    except httpx.HTTPError as exc:
        print(f"✗ HTTP 错误: {exc}")
        return False
    except Exception as exc:
        print(f"✗ 未知错误: {exc}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_api_call()
    print()
    print("=" * 60)
    if success:
        print("✓ API 测试成功！应用可以正常调用模型")
    else:
        print("✗ API 测试失败，请检查配置或联系 API 提供商")
    print("=" * 60)
    sys.exit(0 if success else 1)
