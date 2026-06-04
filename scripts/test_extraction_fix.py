#!/usr/bin/env python3
"""
测试提取效果修复脚本

用法:
    python scripts/test_extraction_fix.py --document-id 123
    python scripts/test_extraction_fix.py --job-id 25 --retry
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import SessionLocal
from app.models import Document, ExtractionJob
from app.api.routes.extractions import _run_job


def test_extraction(document_id: int, query: str = None):
    """测试文档提取"""
    with SessionLocal() as db:
        # 获取文档
        document = db.get(Document, document_id)
        if not document:
            print(f"❌ 文档 #{document_id} 不存在")
            return

        print(f"📄 测试文档: {document.title}")
        print(f"   状态: {document.status}")
        print(f"   类型: {document.source_type}")

        if document.status != "done":
            print(f"❌ 文档状态未完成，无法提取")
            return

        # 使用默认查询或自定义查询
        if not query:
            query = "提取研究目的、材料与方法、实验分组、关键性能指标（含具体数值）、图表数据、主要结论"

        print(f"\n🔍 查询: {query}")

        # 创建提取任务
        job = ExtractionJob(paper_id=document_id, query=query, status="pending")
        db.add(job)
        db.commit()
        db.refresh(job)

        print(f"\n⏳ 开始提取任务 #{job.id}...")
        start_time = time.time()

        try:
            # 运行提取
            job = _run_job(db, job, document)
            elapsed = time.time() - start_time

            print(f"\n✅ 提取完成！耗时 {elapsed:.1f}秒")
            print(f"   状态: {job.status}")

            # 统计结果
            results = job.results
            print(f"\n📊 提取结果统计:")
            print(f"   总结果数: {len(results)}")

            if results:
                high = sum(1 for r in results if r.confidence and r.confidence >= 0.7)
                medium = sum(1 for r in results if r.confidence and 0.4 <= r.confidence < 0.7)
                low = sum(1 for r in results if r.confidence and r.confidence < 0.4)

                print(f"   置信度分布:")
                print(f"     高 (≥0.7): {high} ({high/len(results)*100:.1f}%)")
                print(f"     中 (0.4-0.7): {medium} ({medium/len(results)*100:.1f}%)")
                print(f"     低 (<0.4): {low} ({low/len(results)*100:.1f}%)")

                fallback = sum(1 for r in results if r.extraction_mode == 'fallback_caption_only')
                visual = sum(1 for r in results if r.extraction_mode == 'visual_analysis')
                text = sum(1 for r in results if r.extraction_mode == 'text_extraction')

                print(f"   提取模式:")
                print(f"     Fallback: {fallback}")
                print(f"     视觉分析: {visual}")
                print(f"     文本提取: {text}")

                asset_results = sum(1 for r in results if r.source_type == 'asset')
                text_results = sum(1 for r in results if r.source_type == 'text')

                print(f"   来源类型:")
                print(f"     图表资源: {asset_results}")
                print(f"     纯文本: {text_results}")

                # 显示部分结果样本
                print(f"\n📋 结果样本 (前5条):")
                for i, result in enumerate(results[:5], 1):
                    print(f"\n   {i}. {result.field_name}")
                    print(f"      内容: {result.content[:100]}{'...' if len(result.content) > 100 else ''}")
                    print(f"      置信度: {result.confidence:.2f}")
                    print(f"      模式: {result.extraction_mode}")

                # 警告信息
                if fallback > len(results) * 0.5:
                    print(f"\n⚠️ 警告: 超过50%的结果使用Fallback模式，可能API配置有问题")

                if low > len(results) * 0.5:
                    print(f"\n⚠️ 警告: 超过50%的结果置信度较低，建议重试或检查PDF质量")

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"\n❌ 提取失败！耗时 {elapsed:.1f}秒")
            print(f"   错误: {str(e)}")
            import traceback
            traceback.print_exc()


def retry_job(job_id: int):
    """重试已有的提取任务"""
    with SessionLocal() as db:
        job = db.get(ExtractionJob, job_id)
        if not job:
            print(f"❌ 任务 #{job_id} 不存在")
            return

        document = db.get(Document, job.paper_id)
        if not document:
            print(f"❌ 文档不存在")
            return

        print(f"🔄 重试任务 #{job_id}")
        print(f"   原始查询: {job.query}")
        print(f"   原始状态: {job.status}")
        print(f"   原始结果数: {len(job.results)}")

        # 创建新任务
        new_job = ExtractionJob(paper_id=document.id, query=job.query, status="pending")
        db.add(new_job)
        db.commit()
        db.refresh(new_job)

        print(f"\n⏳ 开始新任务 #{new_job.id}...")
        start_time = time.time()

        try:
            new_job = _run_job(db, new_job, document)
            elapsed = time.time() - start_time

            print(f"\n✅ 重试完成！耗时 {elapsed:.1f}秒")
            print(f"   新结果数: {len(new_job.results)}")
            print(f"   结果变化: {len(new_job.results) - len(job.results):+d}")

            # 对比分析
            old_results = job.results
            new_results = new_job.results

            if old_results and new_results:
                old_avg_confidence = sum(r.confidence or 0 for r in old_results) / len(old_results)
                new_avg_confidence = sum(r.confidence or 0 for r in new_results) / len(new_results)

                print(f"\n📊 对比分析:")
                print(f"   平均置信度: {old_avg_confidence:.2f} → {new_avg_confidence:.2f} ({new_avg_confidence - old_avg_confidence:+.2f})")

                old_fallback = sum(1 for r in old_results if r.extraction_mode == 'fallback_caption_only')
                new_fallback = sum(1 for r in new_results if r.extraction_mode == 'fallback_caption_only')
                print(f"   Fallback数: {old_fallback} → {new_fallback} ({new_fallback - old_fallback:+d})")

                old_visual = sum(1 for r in old_results if r.extraction_mode == 'visual_analysis')
                new_visual = sum(1 for r in new_results if r.extraction_mode == 'visual_analysis')
                print(f"   视觉分析数: {old_visual} → {new_visual} ({new_visual - old_visual:+d})")

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"\n❌ 重试失败！耗时 {elapsed:.1f}秒")
            print(f"   错误: {str(e)}")


def check_api_config():
    """检查API配置"""
    import os
    from app.core import config

    print("🔧 API配置检查:")

    openai_key = os.getenv("OPENAI_API_KEY", config.OPENAI_API_KEY)
    openai_base = os.getenv("OPENAI_BASE_URL", config.OPENAI_BASE_URL)
    openai_model = os.getenv("OPENAI_MODEL", config.OPENAI_MODEL)

    if openai_key:
        print(f"   ✅ OPENAI_API_KEY: {'*' * 10}{openai_key[-4:]}")
    else:
        print(f"   ❌ OPENAI_API_KEY: 未配置")

    print(f"   OPENAI_BASE_URL: {openai_base or '默认'}")
    print(f"   OPENAI_MODEL: {openai_model or '默认'}")

    # 测试API连接
    if openai_key:
        try:
            import httpx
            headers = {"Authorization": f"Bearer {openai_key}"}
            base_url = openai_base or "https://api.openai.com/v1"

            # 简单的models列表测试
            url = f"{base_url.rstrip('/')}/models" if not base_url.endswith("/v1") else f"{base_url}/models"

            with httpx.Client(timeout=10) as client:
                response = client.get(url, headers=headers)
                if response.is_success:
                    print(f"   ✅ API连接正常")
                else:
                    print(f"   ⚠️ API连接异常: {response.status_code}")
        except Exception as e:
            print(f"   ⚠️ API测试失败: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description="测试提取效果修复")
    parser.add_argument("--document-id", type=int, help="要测试的文档ID")
    parser.add_argument("--job-id", type=int, help="要重试的任务ID")
    parser.add_argument("--query", help="自定义提取查询")
    parser.add_argument("--retry", action="store_true", help="重试任务")
    parser.add_argument("--check-config", action="store_true", help="检查API配置")

    args = parser.parse_args()

    if args.check_config:
        check_api_config()

    if args.document_id:
        test_extraction(args.document_id, args.query)

    if args.job_id:
        if args.retry:
            retry_job(args.job_id)
        else:
            print("使用 --retry 标志来重试任务")

    if not any([args.document_id, args.job_id, args.check_config]):
        parser.print_help()


if __name__ == "__main__":
    main()
