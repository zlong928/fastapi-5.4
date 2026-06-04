#!/usr/bin/env python3
"""
测试当前模型配置是否支持视觉分析
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import asyncio
from openai import AsyncOpenAI

async def test_model_config():
    """测试模型配置"""

    print("=" * 80)
    print("🔍 测试当前模型配置")
    print("=" * 80)
    print()

    # 读取配置
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL")

    print("📋 当前配置:")
    print(f"  OPENAI_API_KEY: {api_key[:20]}..." if api_key else "  OPENAI_API_KEY: 未设置")
    print(f"  OPENAI_BASE_URL: {base_url}")
    print(f"  OPENAI_MODEL: {model}")
    print()

    # 检查是否支持视觉分析
    vision_capable_models = [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4-vision-preview",
        "claude-opus-4", "claude-opus-4-8", "claude-sonnet-3.5", "claude-sonnet-4",
        "gemini-pro-vision", "gemini-1.5-pro"
    ]

    supports_vision = any(vm in model.lower() for vm in vision_capable_models)

    if supports_vision:
        print("✅ 模型支持视觉分析")
    else:
        print("⚠️  警告：当前模型可能不支持视觉分析")
        print(f"   模型名称: {model}")
        print(f"   支持视觉的模型包括: {', '.join(vision_capable_models[:6])}")
    print()

    # 测试API连接
    print("🔗 测试API连接...")
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": "Hello, please respond with 'OK' if you receive this message."}
            ],
            max_tokens=50,
            timeout=10
        )

        content = response.choices[0].message.content
        print(f"✅ API连接成功")
        print(f"   响应: {content}")
        print()

    except Exception as e:
        print(f"❌ API连接失败")
        print(f"   错误: {str(e)}")
        print()
        return False

    # 测试视觉分析能力（使用简单的base64图片）
    if supports_vision:
        print("🖼️  测试视觉分析能力...")
        try:
            # 使用一个简单的1x1像素的PNG图片
            simple_image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What do you see in this image? Just say 'I can see an image' if you can process it."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{simple_image}"}}
                        ]
                    }
                ],
                max_tokens=100,
                timeout=15
            )

            content = response.choices[0].message.content
            print(f"✅ 视觉分析功能正常")
            print(f"   响应: {content}")
            print()

        except Exception as e:
            print(f"❌ 视觉分析失败")
            print(f"   错误: {str(e)}")
            print()
            print("💡 可能的原因:")
            print("   1. 当前模型不支持视觉分析")
            print("   2. API端点不支持视觉功能")
            print("   3. 请求格式不正确")
            print()
            return False

    print("=" * 80)
    print("✅ 配置测试完成")
    print("=" * 80)
    return True


async def suggest_config():
    """建议正确的配置"""

    print()
    print("=" * 80)
    print("💡 推荐的模型配置")
    print("=" * 80)
    print()

    print("根据你的base_url (https://muyuan.do)，这是一个第三方API代理。")
    print()
    print("推荐配置1 - 使用Claude Opus 4:")
    print("  OPENAI_API_KEY=claude-opus-4-8")
    print("  OPENAI_BASE_URL=https://muyuan.do")
    print("  OPENAI_MODEL=claude-opus-4-8")
    print()
    print("推荐配置2 - 使用GPT-4o:")
    print("  OPENAI_API_KEY=<你的API密钥>")
    print("  OPENAI_BASE_URL=https://muyuan.do")
    print("  OPENAI_MODEL=gpt-4o")
    print()
    print("推荐配置3 - 使用Claude Sonnet 3.5:")
    print("  OPENAI_API_KEY=<你的API密钥>")
    print("  OPENAI_BASE_URL=https://muyuan.do")
    print("  OPENAI_MODEL=claude-3-5-sonnet-20241022")
    print()
    print("⚠️  注意:")
    print("  - deepseek模型不支持视觉分析，必须更换")
    print("  - 确保API密钥有权限访问所选模型")
    print("  - 修改.env后需要重启FastAPI服务")
    print()


if __name__ == "__main__":
    result = asyncio.run(test_model_config())
    if not result:
        asyncio.run(suggest_config())
