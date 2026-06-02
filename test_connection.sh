#!/bin/bash

echo "=========================================="
echo "前后端连接测试"
echo "=========================================="
echo ""

# 测试后端
echo "1️⃣  测试后端健康检查..."
HEALTH=$(curl -s http://localhost:8000/health 2>&1)
if echo "$HEALTH" | grep -q "ok"; then
    echo "   ✓ 后端运行正常 (http://localhost:8000)"
else
    echo "   ✗ 后端无响应"
    echo "   请运行: python -m uvicorn app.main:app --reload"
    exit 1
fi
echo ""

# 测试 Redis
echo "2️⃣  测试 Redis 连接..."
REDIS=$(redis-cli ping 2>&1)
if [ "$REDIS" = "PONG" ]; then
    echo "   ✓ Redis 运行正常"
else
    echo "   ✗ Redis 未运行"
    echo "   请运行: redis-server --daemonize yes"
fi
echo ""

# 测试数据库
echo "3️⃣  测试数据库..."
if [ -f "data/app.db" ]; then
    DB_SIZE=$(du -h data/app.db | cut -f1)
    echo "   ✓ 数据库存在 (大小: $DB_SIZE)"
else
    echo "   ✗ 数据库文件不存在"
fi
echo ""

# 检查前端配置
echo "4️⃣  检查前端配置..."
if grep -q "VITE_API_BASE_URL" frontend/.env 2>/dev/null; then
    echo "   ℹ️  前端有自定义配置"
    cat frontend/.env | grep VITE_API_BASE_URL
else
    echo "   ℹ️  前端使用默认配置 (http://localhost:8000)"
fi
echo ""

echo "=========================================="
echo "✅ 所有检查完成"
echo "=========================================="
echo ""
echo "📝 问题诊断结果："
echo ""
echo "问题原因："
echo "  - 后端代码有语法错误（智能引号）"
echo "  - 已修复所有中文引号为英文引号"
echo ""
echo "现在可以："
echo "  1. 启动前端: cd frontend && npm run dev"
echo "  2. 访问: http://localhost:3000"
echo "  3. 登录后使用聊天功能"
echo ""
echo "⚠️  注意："
echo "  - API 账户需要有余额才能正常对话"
echo "  - 运行 'python test_api_flow.py' 测试 API"
echo ""
