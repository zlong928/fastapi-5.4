#!/bin/bash
# Redis 启动脚本

REDIS_PATH="/opt/homebrew/bin/redis-server"
REDIS_CLI="/opt/homebrew/bin/redis-cli"

echo "🚀 启动 Redis 服务器..."
$REDIS_PATH --daemonize yes --port 6379

sleep 1

# 验证连接
if $REDIS_CLI ping | grep -q "PONG"; then
    echo "✅ Redis 启动成功！"
    echo "📊 Redis 版本: $($REDIS_PATH --version)"
    echo "🔗 Redis 地址: 127.0.0.1:6379"
else
    echo "❌ Redis 启动失败！"
    exit 1
fi
