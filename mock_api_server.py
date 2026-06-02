#!/usr/bin/env python3
"""模拟 API 服务器用于测试前端显示"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json
import time
import asyncio

app = FastAPI()

@app.post("/v1/chat/completions")
async def mock_chat_completions():
    """模拟流式聊天响应"""

    async def generate():
        # 模拟流式响应
        tokens = ["你好", "！", "这是", "一个", "测试", "响应", "。", "API", "余额", "充足", "后", "就会", "正常", "工作", "了", "。"]

        for token in tokens:
            chunk = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "gpt-5.5",
                "choices": [{
                    "index": 0,
                    "delta": {"content": token},
                    "finish_reason": None
                }]
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.1)  # 模拟延迟

        # 结束标记
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("启动模拟 API 服务器")
    print("=" * 60)
    print("使用方法：")
    print("1. 在 .env 中临时设置：")
    print("   OPENAI_BASE_URL=http://localhost:8888")
    print("   OPENAI_API_KEY=mock-key")
    print("   OPENAI_MODEL=gpt-5.5")
    print("2. 重启你的 FastAPI 应用")
    print("3. 测试前端聊天功能")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8888)
