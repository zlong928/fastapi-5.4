#!/usr/bin/env python3
"""
测试API连接和视觉分析能力
"""

import os
import sys
import json
import requests
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

def test_api_connection():
    """测试API连接"""

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    print("=" * 80)
    print("🔍 测试API连接和视觉分析能力")
    print("=" * 80)
    print()

    print("📋 当前配置:")
    print(f"  API密钥: {api_key[:20]}...{api_key[-10:]}")
    print(f"  端点: {base_url}")
    print(f"  模型: {model}")
    print()

    # 构建API URL
    if base_url.endswith('/v1'):
        api_url = f"{base_url}/chat/completions"
    elif '/v1/' in base_url:
        api_url = f"{base_url}/chat/completions"
    else:
        api_url = f"{base_url}/v1/chat/completions"

    print(f"🔗 API URL: {api_url}")
    print()

    # 测试1: 简单文本对话
    print("=" * 80)
    print("测试 1/3: 简单文本对话")
    print("=" * 80)

    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": "请用中文回复'测试成功'"}
                ],
                "max_tokens": 50
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"✅ 文本对话成功")
            print(f"   响应: {content}")
            print()
        else:
            print(f"❌ 文本对话失败")
            print(f"   状态码: {response.status_code}")
            print(f"   响应: {response.text}")
            print()
            return False

    except Exception as e:
        print(f"❌ 请求失败")
        print(f"   错误: {str(e)}")
        print()
        return False

    # 测试2: JSON输出
    print("=" * 80)
    print("测试 2/3: JSON格式输出")
    print("=" * 80)

    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你必须输出有效的JSON格式"
                    },
                    {
                        "role": "user",
                        "content": '请输出JSON: {"status": "ok", "message": "测试成功"}'
                    }
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 100
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            try:
                json_data = json.loads(content)
                print(f"✅ JSON输出成功")
                print(f"   响应: {json.dumps(json_data, ensure_ascii=False, indent=2)}")
                print()
            except:
                print(f"⚠️  收到响应但不是有效JSON")
                print(f"   响应: {content}")
                print()
        else:
            print(f"❌ JSON输出失败")
            print(f"   状态码: {response.status_code}")
            print(f"   响应: {response.text}")
            print()

    except Exception as e:
        print(f"❌ 请求失败")
        print(f"   错误: {str(e)}")
        print()

    # 测试3: 视觉分析（使用简单的图片）
    print("=" * 80)
    print("测试 3/3: 视觉分析能力（关键测试！）")
    print("=" * 80)

    # 使用一个简单的1x1红色像素PNG图片的base64编码
    simple_red_pixel = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=="

    try:
        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "这是什么颜色的图片？请用中文回答。"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{simple_red_pixel}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 100
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"✅ 视觉分析成功！")
            print(f"   响应: {content}")
            print()
            print("🎉 所有测试通过！你的API配置可以用于图表提取！")
            print()
            return True
        else:
            print(f"❌ 视觉分析失败")
            print(f"   状态码: {response.status_code}")
            print(f"   响应: {response.text[:500]}")
            print()

            if response.status_code == 400:
                print("💡 可能的原因:")
                print("   1. 当前模型不支持视觉分析")
                print("   2. API端点不支持图片输入格式")
                print("   3. 需要使用不同的请求格式")
            elif response.status_code == 401:
                print("💡 可能的原因:")
                print("   1. API密钥无效或过期")
                print("   2. 没有权限使用该模型")
            elif response.status_code == 404:
                print("💡 可能的原因:")
                print("   1. 模型名称错误")
                print("   2. API端点不支持该模型")

            return False

    except Exception as e:
        print(f"❌ 请求失败")
        print(f"   错误: {str(e)}")
        print()
        return False


def print_recommendations():
    """打印推荐配置"""

    print()
    print("=" * 80)
    print("💡 推荐的解决方案")
    print("=" * 80)
    print()

    print("如果视觉分析测试失败，尝试以下配置：")
    print()

    print("方案1: 使用GPT-4o (OpenAI官方)")
    print("-" * 80)
    print("OPENAI_API_KEY=sk-proj-xxxxx  # 从 platform.openai.com 获取")
    print("OPENAI_BASE_URL=https://api.openai.com/v1")
    print("OPENAI_MODEL=gpt-4o")
    print()

    print("方案2: 使用Claude (Anthropic官方)")
    print("-" * 80)
    print("OPENAI_API_KEY=sk-ant-xxxxx  # 从 console.anthropic.com 获取")
    print("OPENAI_BASE_URL=https://api.anthropic.com/v1")
    print("OPENAI_MODEL=claude-3-5-sonnet-20241022")
    print()

    print("方案3: 切换其他第三方代理")
    print("-" * 80)
    print("联系你的API提供商确认:")
    print("  - 是否支持视觉分析")
    print("  - 正确的模型名称")
    print("  - 正确的请求格式")
    print()


if __name__ == "__main__":
    print()
    success = test_api_connection()

    if not success:
        print_recommendations()
    else:
        print("=" * 80)
        print("✅ 下一步操作")
        print("=" * 80)
        print()
        print("1. 重启FastAPI服务:")
        print("   pkill -f uvicorn")
        print("   python -m uvicorn app.main:app --reload")
        print()
        print("2. 测试图像坐标提取链路:")
        print("   docker compose run --rm api pytest tests/test_mineru_image_coordinate_extraction.py tests/test_chart_types.py")
        print()
