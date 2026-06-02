#!/usr/bin/env python3
"""
Quick test script for DeepSeek API integration
"""
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('OPENAI_API_KEY')
base_url = os.getenv('OPENAI_BASE_URL')
model = os.getenv('OPENAI_MODEL')

print("Testing DeepSeek API configuration...")
print(f"Base URL: {base_url}")
print(f"Model: {model}")
print(f"API Key: {api_key[:20]}..." if api_key else "API Key: NOT SET")
print("")

headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json',
}

body = {
    'model': model,
    'messages': [{'role': 'user', 'content': '你好，请用中文回答：1+1等于几？'}],
    'stream': False
}

try:
    response = httpx.post(
        f'{base_url}/v1/chat/completions',
        headers=headers,
        json=body,
        timeout=30
    )

    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        content = data['choices'][0]['message']['content']
        print(f"✅ SUCCESS!")
        print(f"Response: {content}")
    else:
        print(f"❌ Error: {response.text}")

except Exception as e:
    print(f"❌ Exception: {e}")
