#!/bin/bash
# 批量提取功能 - 快速测试脚本

set -e

echo "=========================================="
echo "批量提取功能 - 快速测试"
echo "=========================================="
echo

# 1. 检查环境变量
echo "1. 检查环境变量..."
if grep -q "IMAGE_LLM_PRIMARY=True" .env 2>/dev/null; then
    echo "   ✓ IMAGE_LLM_PRIMARY=True"
else
    echo "   ✗ IMAGE_LLM_PRIMARY 未启用或未设置"
    echo "   请在 .env 中设置: IMAGE_LLM_PRIMARY=True"
    exit 1
fi

# 2. 检查数据库连接
echo
echo "2. 检查数据库连接..."
python3 << 'EOF'
import sys
try:
    from app.db.session import get_db
    next(get_db())
    print("   ✓ 数据库连接正常")
except Exception as e:
    print(f"   ✗ 数据库连接失败: {e}")
    sys.exit(1)
EOF

# 3. 运行并发测试
echo
echo "3. 运行并发处理测试..."
python3 test_batch_concurrent.py || {
    echo "   ✗ 并发测试失败"
    exit 1
}

# 4. 检查前端构建
echo
echo "4. 检查前端..."
if [ -f "frontend/package.json" ]; then
    echo "   ✓ 前端项目存在"
    cd frontend
    if [ ! -d "node_modules" ]; then
        echo "   安装依赖..."
        npm install
    fi
    echo "   ✓ 前端就绪"
    cd ..
else
    echo "   ✗ 前端项目不存在"
fi

# 5. 启动服务建议
echo
echo "=========================================="
echo "测试完成！"
echo "=========================================="
echo
echo "下一步："
echo "1. 启动后端服务:"
echo "   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo
echo "2. 启动前端服务:"
echo "   cd frontend && npm run dev"
echo
echo "3. 访问论文详情页，点击 '批量提取图片' 按钮"
echo
echo "4. 查看日志:"
echo "   tail -f app.log | grep -E 'batch_async|llm_classified'"
echo
echo "=========================================="
