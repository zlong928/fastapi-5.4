#!/bin/bash

# 快速检查模型配置

echo "================================"
echo "🔍 检查当前模型配置"
echo "================================"
echo ""

# 读取配置
API_KEY=$(grep "^OPENAI_API_KEY=" .env | cut -d'=' -f2)
BASE_URL=$(grep "^OPENAI_BASE_URL=" .env | cut -d'=' -f2)
MODEL=$(grep "^OPENAI_MODEL=" .env | cut -d'=' -f2)

echo "📋 当前配置:"
echo "  OPENAI_API_KEY: ${API_KEY:0:20}..."
echo "  OPENAI_BASE_URL: $BASE_URL"
echo "  OPENAI_MODEL: $MODEL"
echo ""

# 检查是否支持视觉
echo "🖼️  视觉分析支持检查:"
if [[ "$MODEL" == *"gpt-4o"* ]] || [[ "$MODEL" == *"claude-opus"* ]] || [[ "$MODEL" == *"claude-sonnet"* ]] || [[ "$MODEL" == *"vision"* ]] || [[ "$MODEL" == *"claude-3"* ]]; then
    echo "  ✅ 模型 '$MODEL' 支持视觉分析"
else
    echo "  ⚠️  警告：模型 '$MODEL' 可能不支持视觉分析"
    echo ""
    echo "  支持视觉的模型包括："
    echo "    - gpt-4o, gpt-4o-mini"
    echo "    - gpt-4-turbo, gpt-4-vision-preview"
    echo "    - claude-opus-4, claude-opus-4-8"
    echo "    - claude-sonnet-3.5, claude-3-5-sonnet"
    echo ""
fi

# 检查API密钥格式
echo ""
echo "🔑 API密钥检查:"
if [ ${#API_KEY} -lt 20 ]; then
    echo "  ⚠️  警告：API密钥长度过短 (${#API_KEY}字符)"
    echo "     可能不是有效的API密钥"
elif [ "$API_KEY" == "$MODEL" ]; then
    echo "  ❌ 错误：API_KEY和MODEL相同！"
    echo "     API_KEY应该是密钥，而不是模型名称"
    echo "     请从API提供商获取正确的密钥"
else
    echo "  ✅ API密钥格式看起来正常 (长度: ${#API_KEY}字符)"
fi

echo ""
echo "================================"
echo "💡 建议的配置"
echo "================================"
echo ""

if [ "$API_KEY" == "$MODEL" ] || [ ${#API_KEY} -lt 20 ]; then
    echo "⚠️  需要修复配置！"
    echo ""
    echo "推荐配置 (使用第三方代理):"
    echo ""
    echo "OPENAI_API_KEY=<你的真实API密钥>  # 从 $BASE_URL 获取"
    echo "OPENAI_BASE_URL=$BASE_URL"
    echo "OPENAI_MODEL=claude-opus-4-8  # 或 gpt-4o"
    echo ""
    echo "如果你没有API密钥，请："
    echo "1. 联系 $BASE_URL 的管理员获取密钥"
    echo "2. 或者注册OpenAI/Anthropic官方账号"
else
    echo "✅ 配置看起来正常"
    echo ""
    echo "如果提取仍然失败，检查："
    echo "1. API密钥是否有效"
    echo "2. 模型是否支持视觉分析"
    echo "3. API配额是否用完"
    echo "4. 网络连接是否正常"
fi

echo ""
echo "================================"
echo "🚀 下一步"
echo "================================"
echo ""
echo "1. 修改 .env 文件（如果需要）："
echo "   nano .env"
echo ""
echo "2. 重启FastAPI服务："
echo "   pkill -f uvicorn"
echo "   python -m uvicorn app.main:app --reload"
echo ""
echo "3. 测试提取效果："
echo "   python scripts/quick_verify_extraction.py --document-id <ID>"
echo ""
