#!/usr/bin/env python3
"""
诊断提取效果下降的脚本

用法:
    python scripts/diagnose_extraction.py --job-ids 14,25
    python scripts/diagnose_extraction.py --document-id 123 --compare-last 2
"""
import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func, text
from app.db.session import SessionLocal


def compare_jobs(job_ids: list[int]):
    """对比多个提取任务的结果"""
    with SessionLocal() as db:
        query = text("""
            SELECT
                ej.id as job_id,
                ej.created_at,
                ej.query,
                ej.status,
                d.title as paper_title,
                COUNT(er.id) as total_results,
                COUNT(CASE WHEN er.confidence >= 0.7 THEN 1 END) as high_confidence,
                COUNT(CASE WHEN er.confidence >= 0.4 AND er.confidence < 0.7 THEN 1 END) as medium_confidence,
                COUNT(CASE WHEN er.confidence < 0.4 THEN 1 END) as low_confidence,
                COUNT(CASE WHEN er.extraction_mode = 'fallback_caption_only' THEN 1 END) as fallback_count,
                COUNT(CASE WHEN er.extraction_mode = 'visual_analysis' THEN 1 END) as visual_analysis_count,
                COUNT(CASE WHEN er.extraction_mode = 'text_extraction' THEN 1 END) as text_extraction_count,
                COUNT(CASE WHEN er.source_type = 'asset' THEN 1 END) as asset_results,
                COUNT(CASE WHEN er.source_type = 'text' THEN 1 END) as text_results
            FROM extraction_jobs ej
            LEFT JOIN extraction_results er ON er.job_id = ej.id AND er.is_deleted = false
            LEFT JOIN documents d ON d.id = ej.paper_id
            WHERE ej.id = ANY(:job_ids)
            GROUP BY ej.id, ej.created_at, ej.query, ej.status, d.title
            ORDER BY ej.created_at ASC
        """)

        results = db.execute(query, {"job_ids": job_ids}).fetchall()

        print("\n" + "="*100)
        print("提取任务对比分析")
        print("="*100)

        for row in results:
            print(f"\n任务 #{row.job_id} - {row.created_at}")
            print(f"  论文: {row.paper_title}")
            print(f"  查询: {row.query}")
            print(f"  状态: {row.status}")
            print(f"  总结果数: {row.total_results}")
            print(f"  置信度分布:")
            print(f"    - 高 (≥0.7): {row.high_confidence} ({row.high_confidence/max(row.total_results, 1)*100:.1f}%)")
            print(f"    - 中 (0.4-0.7): {row.medium_confidence} ({row.medium_confidence/max(row.total_results, 1)*100:.1f}%)")
            print(f"    - 低 (<0.4): {row.low_confidence} ({row.low_confidence/max(row.total_results, 1)*100:.1f}%)")
            print(f"  提取模式:")
            print(f"    - Fallback: {row.fallback_count}")
            print(f"    - 视觉分析: {row.visual_analysis_count}")
            print(f"    - 文本提取: {row.text_extraction_count}")
            print(f"  来源类型:")
            print(f"    - 图表资源: {row.asset_results}")
            print(f"    - 纯文本: {row.text_results}")

        # 分析差异
        if len(results) >= 2:
            print("\n" + "-"*100)
            print("差异分析:")
            baseline = results[0]
            for current in results[1:]:
                diff = current.total_results - baseline.total_results
                diff_pct = (diff / max(baseline.total_results, 1)) * 100

                print(f"\n  任务 #{current.job_id} vs 任务 #{baseline.job_id}:")
                print(f"    总结果数变化: {diff:+d} ({diff_pct:+.1f}%)")

                fallback_diff = current.fallback_count - baseline.fallback_count
                if fallback_diff > 0:
                    print(f"    ⚠️ Fallback增加: {fallback_diff:+d} (可能是API调用失败)")

                visual_diff = current.visual_analysis_count - baseline.visual_analysis_count
                if visual_diff < 0:
                    print(f"    ⚠️ 视觉分析减少: {visual_diff:+d} (图表提取可能失败)")

                confidence_drop = (current.low_confidence / max(current.total_results, 1)) - (baseline.low_confidence / max(baseline.total_results, 1))
                if confidence_drop > 0.2:
                    print(f"    ⚠️ 低置信度结果占比增加: {confidence_drop*100:+.1f}% (质量下降)")


def check_document_assets(document_id: int):
    """检查文档的图表资源提取情况"""
    with SessionLocal() as db:
        query = text("""
            SELECT
                da.id,
                da.asset_type,
                da.page_number,
                da.label,
                SUBSTRING(da.caption, 1, 80) as caption_preview,
                da.metadata_json::jsonb->>'source' as source,
                da.metadata_json::jsonb->>'confidence' as confidence,
                da.metadata_json::jsonb->>'evidence_type' as evidence_type,
                da.metadata_json::jsonb->>'agent_analyzed' as agent_analyzed,
                da.metadata_json::jsonb->>'agent_analysis_status' as agent_analysis_status
            FROM document_assets da
            WHERE da.document_id = :document_id
              AND da.asset_type IN ('figure', 'table', 'page_snapshot')
            ORDER BY da.page_number, da.id
        """)

        results = db.execute(query, {"document_id": document_id}).fetchall()

        print("\n" + "="*100)
        print(f"文档 #{document_id} 的图表资源")
        print("="*100)

        asset_types = {}
        for row in results:
            asset_types[row.asset_type] = asset_types.get(row.asset_type, 0) + 1

            print(f"\n资源 #{row.id} - 第{row.page_number}页")
            print(f"  类型: {row.asset_type}")
            print(f"  标签: {row.label}")
            print(f"  标题: {row.caption_preview}")
            print(f"  来源: {row.source}")
            print(f"  证据类型: {row.evidence_type}")
            print(f"  置信度: {row.confidence}")
            print(f"  Agent分析: {row.agent_analyzed} ({row.agent_analysis_status})")

        print("\n" + "-"*100)
        print("统计:")
        for asset_type, count in asset_types.items():
            print(f"  {asset_type}: {count}")

        # 检查是否有fallback_snapshot
        fallback_count = sum(1 for r in results if r.source == 'fallback_snapshot')
        if fallback_count > 0:
            print(f"\n  ⚠️ 发现 {fallback_count} 个fallback快照（正常图表提取可能失败）")

        # 检查Agent分析失败
        analysis_failed = sum(1 for r in results if r.agent_analysis_status == 'failed')
        if analysis_failed > 0:
            print(f"  ⚠️ {analysis_failed} 个资源Agent分析失败")


def check_extraction_events(document_id: int, limit: int = 10):
    """查看提取任务的事件日志"""
    with SessionLocal() as db:
        query = text("""
            SELECT
                de.event_type,
                de.message,
                de.event_metadata,
                de.created_at
            FROM document_events de
            WHERE de.document_id = :document_id
              AND de.event_type LIKE '%extraction%'
            ORDER BY de.created_at DESC
            LIMIT :limit
        """)

        results = db.execute(query, {"document_id": document_id, "limit": limit}).fetchall()

        print("\n" + "="*100)
        print(f"文档 #{document_id} 的提取事件日志（最近{limit}条）")
        print("="*100)

        for row in results:
            print(f"\n[{row.created_at}] {row.event_type}")
            print(f"  {row.message}")
            if row.event_metadata:
                print(f"  元数据: {row.event_metadata}")


def main():
    parser = argparse.ArgumentParser(description="诊断提取效果下降")
    parser.add_argument("--job-ids", help="要对比的任务ID，逗号分隔（如: 14,25）")
    parser.add_argument("--document-id", type=int, help="文档ID")
    parser.add_argument("--compare-last", type=int, help="对比最近N个提取任务")
    parser.add_argument("--check-assets", action="store_true", help="检查图表资源")
    parser.add_argument("--check-events", action="store_true", help="查看事件日志")

    args = parser.parse_args()

    if args.job_ids:
        job_ids = [int(x.strip()) for x in args.job_ids.split(",")]
        compare_jobs(job_ids)

    elif args.document_id and args.compare_last:
        with SessionLocal() as db:
            query = text("""
                SELECT id FROM extraction_jobs
                WHERE paper_id = :document_id
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            results = db.execute(query, {"document_id": args.document_id, "limit": args.compare_last}).fetchall()
            job_ids = [row.id for row in results]

            if job_ids:
                compare_jobs(job_ids)
            else:
                print(f"文档 #{args.document_id} 没有提取任务")

    if args.document_id and args.check_assets:
        check_document_assets(args.document_id)

    if args.document_id and args.check_events:
        check_extraction_events(args.document_id)

    if not any([args.job_ids, args.document_id]):
        parser.print_help()


if __name__ == "__main__":
    main()
