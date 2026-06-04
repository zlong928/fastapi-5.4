#!/usr/bin/env python3
"""
快速验证图表提取改进效果
使用方法：python scripts/quick_verify_extraction.py --document-id <ID>
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, func, and_
from app.db.session import get_db_context
from app.models import ExtractionJob, ExtractionResult, Document
from datetime import datetime
import argparse


async def verify_extraction_improvement(document_id: int):
    """验证提取改进效果"""

    print(f"\n{'='*80}")
    print(f"📊 验证文档 #{document_id} 的图表提取效果")
    print(f"{'='*80}\n")

    async with get_db_context() as db:
        # 1. 获取文档信息
        doc = await db.get(Document, document_id)
        if not doc:
            print(f"❌ 文档 #{document_id} 不存在")
            return

        print(f"📄 文档: {doc.title or 'Untitled'}")
        print(f"   上传时间: {doc.created_at}")
        print(f"   状态: {doc.status}\n")

        # 2. 获取所有提取任务
        result = await db.execute(
            select(ExtractionJob)
            .where(ExtractionJob.paper_id == document_id)
            .order_by(ExtractionJob.created_at.desc())
        )
        jobs = result.scalars().all()

        if not jobs:
            print("❌ 该文档没有提取任务记录")
            return

        print(f"📋 找到 {len(jobs)} 个提取任务:\n")

        # 3. 分析每个任务
        for idx, job in enumerate(jobs, 1):
            print(f"{'─'*80}")
            print(f"任务 #{idx}: Job #{job.id}")
            print(f"创建时间: {job.created_at}")
            print(f"状态: {job.status}")
            print(f"{'─'*80}")

            # 统计提取结果
            result_count = await db.execute(
                select(func.count(ExtractionResult.id))
                .where(ExtractionResult.job_id == job.id)
            )
            total_results = result_count.scalar()

            # 分析结果质量
            results = await db.execute(
                select(ExtractionResult)
                .where(ExtractionResult.job_id == job.id)
                .limit(100)
            )
            results_list = results.scalars().all()

            if not results_list:
                print("⚠️  没有提取结果\n")
                continue

            # 质量指标
            has_numbers = sum(1 for r in results_list if any(c.isdigit() for c in (r.content or "")))
            has_comparison = sum(1 for r in results_list if any(word in (r.content or "") for word in ["比", "高于", "低于", "%", "倍"]))
            has_english = sum(1 for r in results_list if any(c.isalpha() and ord(c) < 128 for c in (r.evidence or "")))
            has_structured = sum(1 for r in results_list if r.structured_data is not None)
            avg_content_length = sum(len(r.content or "") for r in results_list) / len(results_list) if results_list else 0

            high_conf = sum(1 for r in results_list if r.confidence and r.confidence > 0.7)

            print(f"\n📊 统计指标:")
            print(f"   总结果数: {total_results}")
            print(f"   样本数: {len(results_list)}")
            print(f"\n✅ 质量指标:")
            print(f"   包含数值: {has_numbers}/{len(results_list)} ({has_numbers/len(results_list)*100:.1f}%)")
            print(f"   包含对比: {has_comparison}/{len(results_list)} ({has_comparison/len(results_list)*100:.1f}%)")
            print(f"   包含英文: {has_english}/{len(results_list)} ({has_english/len(results_list)*100:.1f}%)")
            print(f"   结构化数据: {has_structured}/{len(results_list)} ({has_structured/len(results_list)*100:.1f}%)")
            print(f"   高置信度(>0.7): {high_conf}/{len(results_list)} ({high_conf/len(results_list)*100:.1f}%)")
            print(f"   平均content长度: {avg_content_length:.0f} 字符")

            # 显示示例结果
            print(f"\n📝 结果示例 (前3条):\n")
            for i, result in enumerate(results_list[:3], 1):
                print(f"  [{i}] {result.field_name}")
                content_preview = (result.content or "")[:200]
                print(f"      内容: {content_preview}{'...' if len(result.content or '') > 200 else ''}")
                if result.evidence:
                    evidence_preview = result.evidence[:150]
                    print(f"      证据: {evidence_preview}{'...' if len(result.evidence) > 150 else ''}")
                print(f"      置信度: {result.confidence or 'N/A'}")
                if result.structured_data:
                    print(f"      结构化: ✅ 有")
                print()

            print()

        # 4. 对比最新和之前的任务
        if len(jobs) >= 2:
            print(f"\n{'='*80}")
            print(f"📈 改进对比 (最新 vs 之前)")
            print(f"{'='*80}\n")

            latest_job = jobs[0]
            previous_job = jobs[1]

            # 获取两个任务的结果统计
            latest_count = await db.execute(
                select(func.count(ExtractionResult.id))
                .where(ExtractionResult.job_id == latest_job.id)
            )
            latest_total = latest_count.scalar()

            previous_count = await db.execute(
                select(func.count(ExtractionResult.id))
                .where(ExtractionResult.job_id == previous_job.id)
            )
            previous_total = previous_count.scalar()

            improvement = ((latest_total - previous_total) / previous_total * 100) if previous_total > 0 else 0

            print(f"结果数量:")
            print(f"  之前: {previous_total}")
            print(f"  最新: {latest_total}")
            print(f"  变化: {'+' if improvement > 0 else ''}{improvement:.1f}%")
            print()

            if improvement > 50:
                print("✨ 太棒了！提取结果显著增加！")
            elif improvement > 20:
                print("✅ 不错！提取效果有明显改善")
            elif improvement > 0:
                print("📈 有所改进")
            else:
                print("⚠️  结果数量没有增加，可能需要进一步调查")

        # 5. 总体评估
        print(f"\n{'='*80}")
        print(f"🎯 总体评估")
        print(f"{'='*80}\n")

        latest_job = jobs[0]
        latest_results = await db.execute(
            select(ExtractionResult)
            .where(ExtractionResult.job_id == latest_job.id)
        )
        latest_list = latest_results.scalars().all()

        if not latest_list:
            print("❌ 最新任务没有提取结果")
            return

        # 计算总体质量分数
        score = 0
        max_score = 100

        # 数量得分 (30分)
        if len(latest_list) >= 25:
            score += 30
        elif len(latest_list) >= 15:
            score += 20
        elif len(latest_list) >= 10:
            score += 10

        # 数值覆盖率 (25分)
        has_numbers_ratio = sum(1 for r in latest_list if any(c.isdigit() for c in (r.content or ""))) / len(latest_list)
        score += int(has_numbers_ratio * 25)

        # 对比关系覆盖率 (20分)
        has_comparison_ratio = sum(1 for r in latest_list if any(word in (r.content or "") for word in ["比", "高于", "低于", "%", "倍"])) / len(latest_list)
        score += int(has_comparison_ratio * 20)

        # 中文纯度 (15分) - 英文越少越好
        has_english_ratio = sum(1 for r in latest_list if any(c.isalpha() and ord(c) < 128 for c in (r.evidence or ""))) / len(latest_list)
        score += int((1 - has_english_ratio) * 15)

        # 结构化数据 (10分)
        has_structured_ratio = sum(1 for r in latest_list if r.structured_data is not None) / len(latest_list)
        score += int(has_structured_ratio * 10)

        print(f"总体质量分数: {score}/{max_score}")
        print()

        if score >= 80:
            print("🎉 优秀！提取效果非常好！")
            print("✅ 图表覆盖完整")
            print("✅ 数据精确详细")
            print("✅ 中文表达规范")
        elif score >= 60:
            print("👍 良好！提取效果不错")
            print("✅ 大部分图表已覆盖")
            print("✅ 数据较为详细")
        elif score >= 40:
            print("⚠️  一般，还有提升空间")
            print("💡 建议检查：")
            print("   - 是否所有图表都被提取？")
            print("   - content是否包含具体数值？")
            print("   - 是否有对比关系描述？")
        else:
            print("❌ 需要改进")
            print("💡 建议：")
            print("   - 检查API配置是否正确")
            print("   - 确认使用的是支持视觉的模型")
            print("   - 查看日志排查错误")

        print()


async def main():
    parser = argparse.ArgumentParser(description="快速验证图表提取改进效果")
    parser.add_argument("--document-id", type=int, required=True, help="文档ID")

    args = parser.parse_args()

    await verify_extraction_improvement(args.document_id)

    print(f"\n{'='*80}")
    print("验证完成！")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
