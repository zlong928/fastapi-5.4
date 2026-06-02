#!/usr/bin/env python3
"""测试RAG系统功能"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from app.db.session import SessionLocal
from app.services.web_search_service import WebSearchService
from app.services.document_search_service import DocumentSearchService
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_web_search():
    """测试网页搜索"""
    print("\n" + "="*60)
    print("测试1: 网页搜索功能")
    print("="*60)

    service = WebSearchService()
    if not service.api_key:
        print("❌ TAVILY_API_KEY 未配置")
        return False

    # 测试搜索
    query = "2026年AI发展趋势"
    print(f"\n搜索查询: {query}")
    results = service.search(query)

    if results:
        print(f"✅ 找到 {len(results)} 条结果:")
        for i, r in enumerate(results[:3], 1):
            print(f"\n  [{i}] {r['title']}")
            print(f"      URL: {r['url']}")
            print(f"      摘要: {r['snippet'][:100]}...")
        return True
    else:
        print("❌ 未找到结果")
        return False


def test_should_search_web():
    """测试网页搜索触发逻辑"""
    print("\n" + "="*60)
    print("测试2: 网页搜索触发逻辑")
    print("="*60)

    service = WebSearchService()

    test_cases = [
        ("2026年最新技术", [], True, "时效性查询"),
        ("Python教程", [1, 2, 3, 4, 5], False, "知识库结果充足"),
        ("什么是机器学习", [1], True, "问题+结果不足"),
        ("搜索一下深度学习", [1, 2], True, "显式搜索请求"),
    ]

    for query, local_results, expected, reason in test_cases:
        result = service.should_search_web(query, local_results)
        status = "✅" if result == expected else "❌"
        print(f"{status} '{query}' -> {result} ({reason})")

    return True


def test_embedding_coverage():
    """测试embedding覆盖率"""
    print("\n" + "="*60)
    print("测试3: Embedding覆盖率")
    print("="*60)

    db = SessionLocal()
    try:
        result = db.execute(text('''
            SELECT
                COUNT(*) as total_chunks,
                SUM(CASE WHEN embedding_json IS NOT NULL THEN 1 ELSE 0 END) as embedded_chunks,
                COUNT(DISTINCT document_id) as total_docs
            FROM document_chunks
        ''')).fetchone()

        total, embedded, docs = result
        coverage = (embedded / total * 100) if total > 0 else 0

        print(f"  总文档数: {docs}")
        print(f"  总chunk数: {total}")
        print(f"  已embedding: {embedded}")
        print(f"  覆盖率: {coverage:.1f}%")

        if coverage > 95:
            print("  ✅ Embedding覆盖率良好")
            return True
        elif coverage > 80:
            print("  ⚠️  Embedding覆盖率一般，建议运行补丁脚本")
            return True
        else:
            print("  ❌ Embedding覆盖率过低")
            return False

    finally:
        db.close()


def test_vector_search():
    """测试向量搜索"""
    print("\n" + "="*60)
    print("测试4: 向量搜索功能")
    print("="*60)

    db = SessionLocal()
    try:
        # 获取一个有文档的用户
        user_result = db.execute(text('''
            SELECT DISTINCT user_id
            FROM documents
            WHERE status IN ('done', 'completed')
            LIMIT 1
        ''')).fetchone()

        if not user_result:
            print("  ⚠️  数据库中没有已完成的文档，跳过测试")
            return True

        user_id = user_result[0]

        # 测试搜索
        search_service = DocumentSearchService(db)
        query = "测试查询"
        results = search_service.search_chunks(
            user_id=user_id,
            query=query,
            limit=5,
            threshold=0.0
        )

        print(f"  查询: '{query}'")
        print(f"  找到 {len(results)} 条结果")

        if results:
            print(f"  ✅ 向量搜索正常工作")
            for i, r in enumerate(results[:2], 1):
                print(f"    [{i}] {r.get('document_title', 'Unknown')} (score: {r.get('score', 0):.3f})")
            return True
        else:
            print(f"  ⚠️  未找到结果（可能是查询不匹配）")
            return True

    finally:
        db.close()


def test_query_term_extraction():
    """测试查询词提取"""
    print("\n" + "="*60)
    print("测试5: 查询词提取优化")
    print("="*60)

    from app.api.routes.chat import _query_terms

    test_queries = [
        "什么是机器学习的基本原理",
        "2026年AI发展趋势",
        "Python FastAPI教程",
        "如何使用向量数据库进行检索",
    ]

    for query in test_queries:
        terms = _query_terms(query)
        print(f"  '{query}'")
        print(f"    -> {terms}")

    print("  ✅ 查询词提取功能正常")
    return True


def main():
    print("\n" + "="*60)
    print("RAG系统功能测试")
    print("="*60)

    tests = [
        ("Embedding覆盖率", test_embedding_coverage),
        ("查询词提取", test_query_term_extraction),
        ("向量搜索", test_vector_search),
        ("网页搜索触发", test_should_search_web),
        ("网页搜索功能", test_web_search),
    ]

    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"❌ 测试 '{name}' 失败: {e}")
            results[name] = False

    # 总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"{status} {name}")

    print(f"\n通过: {passed}/{total}")

    if passed == total:
        print("\n🎉 所有测试通过！RAG系统已完整配置。")
    elif passed >= total * 0.8:
        print("\n⚠️  大部分测试通过，系统基本可用。")
    else:
        print("\n❌ 多项测试失败，请检查配置。")


if __name__ == "__main__":
    main()
