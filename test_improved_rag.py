#!/usr/bin/env python3
"""测试改进后的RAG系统 - 验证知识库优先，网页搜索作为后备"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from app.db.session import SessionLocal
from app.services.document_search_service import DocumentSearchService
from app.services.web_search_service import WebSearchService
from app.api.routes.chat import _query_terms, _keyword_chunk_sources
from sqlalchemy import text


def test_query_terms():
    """测试关键词提取"""
    print("=" * 60)
    print("测试1: 关键词提取")
    print("=" * 60)

    test_cases = [
        "毕业设计相关文档",
        "由系统知识库中的毕业相关文件",
        "什么是机器学习",
        "2026年最新AI趋势"
    ]

    for query in test_cases:
        terms = _query_terms(query)
        print(f"\n查询: {query}")
        print(f"提取关键词: {terms}")
        print(f"关键词数量: {len(terms)}")


def test_local_search():
    """测试本地知识库搜索"""
    print("\n" + "=" * 60)
    print("测试2: 本地知识库搜索")
    print("=" * 60)

    db = SessionLocal()
    try:
        # 检查文档数量
        doc_count = db.execute(text(
            "SELECT COUNT(*) FROM documents WHERE is_deleted = 0"
        )).scalar()
        print(f"\n✅ 知识库文档总数: {doc_count}")

        # 检查chunk数量
        chunk_count = db.execute(text(
            "SELECT COUNT(*) FROM document_chunks"
        )).scalar()
        print(f"✅ 文档块总数: {chunk_count}")

        # 测试搜索
        test_queries = [
            "毕业",
            "毕业设计",
            "评阅"
        ]

        search_service = DocumentSearchService(db)

        for query in test_queries:
            print(f"\n查询: '{query}'")

            # 向量搜索
            try:
                hits = search_service.search_chunks(
                    user_id=1,
                    query=query,
                    limit=5,
                    threshold=0.0
                )
                print(f"  向量搜索结果: {len(hits)} 条")
                for i, hit in enumerate(hits[:3], 1):
                    print(f"    [{i}] {hit.get('document_title', '未知')} (分数: {hit.get('score', 0):.3f})")
            except Exception as e:
                print(f"  向量搜索失败: {e}")

            # 关键词搜索
            keyword_hits = _keyword_chunk_sources(db, user_id=1, query=query, limit=5, document_id=None)
            print(f"  关键词搜索结果: {len(keyword_hits)} 条")
            for i, hit in enumerate(keyword_hits[:3], 1):
                print(f"    [{i}] {hit.get('document_title', '未知')} (分数: {hit.get('score', 0):.3f})")

    finally:
        db.close()


def test_web_search_trigger():
    """测试网页搜索触发逻辑"""
    print("\n" + "=" * 60)
    print("测试3: 网页搜索触发逻辑")
    print("=" * 60)

    web_service = WebSearchService()

    test_cases = [
        {
            "question": "毕业设计相关文档",
            "local_results": [
                {"score": 2.5, "document_title": "毕业设计鉴定意见"},
                {"score": 2.3, "document_title": "毕业设计评阅表"},
            ],
            "expected": False,
            "reason": "知识库有充足结果"
        },
        {
            "question": "什么是量子计算",
            "local_results": [],
            "expected": True,
            "reason": "知识库无结果"
        },
        {
            "question": "什么是深度学习",
            "local_results": [{"score": 0.2, "document_title": "某文档"}],
            "expected": True,
            "reason": "知识库结果质量太低"
        },
        {
            "question": "2026年最新AI趋势",
            "local_results": [{"score": 1.0, "document_title": "AI基础"}],
            "expected": True,
            "reason": "时效性查询且结果少"
        },
        {
            "question": "搜索一下机器学习",
            "local_results": [{"score": 2.0, "document_title": "ML教程"}],
            "expected": True,
            "reason": "用户明确要求网页搜索"
        },
    ]

    for case in test_cases:
        should_search = web_service.should_search_web(
            case["question"],
            case["local_results"]
        )

        status = "✅" if should_search == case["expected"] else "❌"
        print(f"\n{status} 查询: {case['question']}")
        print(f"   知识库结果: {len(case['local_results'])} 条")
        if case["local_results"]:
            max_score = max(r.get("score", 0) for r in case["local_results"])
            print(f"   最高分数: {max_score:.2f}")
        print(f"   是否触发网页搜索: {should_search}")
        print(f"   预期: {case['expected']} ({case['reason']})")


def test_integration():
    """集成测试：模拟完整查询流程"""
    print("\n" + "=" * 60)
    print("测试4: 集成测试")
    print("=" * 60)

    db = SessionLocal()
    try:
        from app.api.routes.chat import collect_sources
        from app.core import config as app_config

        test_queries = [
            ("毕业设计", "应该从知识库检索到结果"),
            ("量子计算机", "知识库可能没有，应触发网页搜索"),
        ]

        for query, description in test_queries:
            print(f"\n查询: '{query}'")
            print(f"说明: {description}")

            sources = collect_sources(
                db=db,
                user_id=1,
                question=query,
                limit=5,
                document_id=None,
                threshold=0.0
            )

            local_sources = [s for s in sources if s.get("source_type") != "web_search"]
            web_sources = [s for s in sources if s.get("source_type") == "web_search"]

            print(f"  本地来源: {len(local_sources)} 条")
            if local_sources:
                for i, s in enumerate(local_sources[:3], 1):
                    print(f"    [{i}] {s.get('document_title', '未知')} (分数: {s.get('score', 0):.3f})")

            print(f"  网页来源: {len(web_sources)} 条")
            if web_sources:
                for i, s in enumerate(web_sources[:3], 1):
                    print(f"    [网-{i}] {s.get('document_title', '未知')[:50]}")

    finally:
        db.close()


def main():
    print("🔍 测试改进后的RAG系统")
    print("目标: 确保知识库优先，网页搜索仅作为后备\n")

    try:
        test_query_terms()
        test_local_search()
        test_web_search_trigger()
        test_integration()

        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)
        print("\n总结:")
        print("1. 关键词提取现在保留更多有意义的词（包括单字）")
        print("2. 关键词搜索现在同时搜索文档标题、文件名和内容")
        print("3. 网页搜索触发条件更加保守，仅在以下情况触发:")
        print("   - 知识库完全没有结果")
        print("   - 知识库结果质量太低（分数<0.3）")
        print("   - 用户明确要求网页搜索")
        print("   - 时效性查询且知识库结果少于3条")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
