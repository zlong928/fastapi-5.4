"""网页搜索服务 - 使用Tavily API"""
from __future__ import annotations
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class WebSearchService:
    """网页搜索服务，使用Tavily API"""

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        self.max_results = max_results
        self._client = None

    def _get_client(self):
        """懒加载Tavily客户端"""
        if self._client is None and self.api_key:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self.api_key)
                logger.info("Tavily client initialized successfully")
            except ImportError:
                logger.error("tavily-python not installed. Run: pip install tavily-python")
                self._client = False
            except Exception as e:
                logger.error(f"Failed to initialize Tavily client: {e}")
                self._client = False
        return self._client if self._client is not False else None

    def search(self, query: str, timeout: int = 10) -> list[dict[str, Any]]:
        """
        搜索网页并返回结果

        Args:
            query: 搜索查询
            timeout: 超时时间（秒）

        Returns:
            搜索结果列表，格式：
            [
                {
                    "title": "页面标题",
                    "url": "https://...",
                    "snippet": "摘要内容",
                    "content": "完整内容",
                    "score": 相关性分数
                }
            ]
        """
        client = self._get_client()
        if not client:
            logger.warning("Tavily client not available, skipping web search")
            return []

        try:
            # Tavily搜索，专为AI RAG优化
            response = client.search(
                query=query,
                max_results=self.max_results,
                search_depth="basic",  # "basic" 或 "advanced"
                include_raw_content=False,  # 不需要完整HTML
                include_answer=False,  # 不需要AI生成的答案
            )

            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),  # Tavily已优化的摘要
                    "content": item.get("content", ""),
                    "score": item.get("score", 0.0),
                    "source": self._extract_domain(item.get("url", ""))
                })

            logger.info(f"Tavily search for '{query}': found {len(results)} results")
            return results

        except Exception as e:
            logger.warning(f"Web search failed for query '{query}': {e}")
            return []

    def _extract_domain(self, url: str) -> str:
        """从URL提取域名"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or url
        except Exception:
            return url

    def should_search_web(
        self,
        question: str,
        local_results: list,
        min_results_threshold: int = 1,  # 降低到1，只有真的没结果才触发
        min_score_threshold: float = 0.3  # 新增：分数阈值
    ) -> bool:
        """
        判断是否需要网页搜索

        核心原则：知识库优先，网页搜索只作为真正缺失时的后备

        Args:
            question: 用户问题
            local_results: 知识库搜索结果
            min_results_threshold: 最少结果数阈值（默认1，即有结果就不搜网页）
            min_score_threshold: 最低分数阈值（结果质量太低时才触发）

        Returns:
            是否需要网页搜索
        """
        # 0. 如果没有配置API key，不搜索
        if not self.api_key:
            return False

        # 1. 知识库完全没有结果 -> 触发网页搜索
        if len(local_results) < min_results_threshold:
            logger.info(f"No local results found ({len(local_results)} < {min_results_threshold}), enabling web search")
            return True

        # 2. 知识库有结果但质量很低（所有结果分数都<0.3）-> 触发网页搜索
        if local_results:
            max_score = max((r.get("score", 0.0) for r in local_results), default=0.0)
            if max_score < min_score_threshold:
                logger.info(f"Local results have low quality (max_score={max_score:.3f} < {min_score_threshold}), enabling web search")
                return True

        # 3. 用户明确要求网页搜索（包含显式搜索意图）
        explicit_web_keywords = [
            "搜索", "上网查", "网上", "互联网", "百度", "谷歌",
            "search web", "search online", "google", "look up online"
        ]
        if any(kw in question.lower() for kw in explicit_web_keywords):
            logger.info(f"Explicit web search request detected in '{question}'")
            return True

        # 4. 时效性查询 + 知识库结果少 -> 触发网页搜索
        time_keywords = [
            "最新", "今天", "现在", "当前", "最近", "刚刚",
            "2026", "今年", "本月", "本周",
            "latest", "current", "recent", "today", "now", "this year"
        ]
        has_time_keyword = any(kw in question.lower() for kw in time_keywords)
        if has_time_keyword and len(local_results) < 3:
            logger.info(f"Time-sensitive query with few results ({len(local_results)} results), enabling web search")
            return True

        # 默认：知识库有足够结果，不触发网页搜索
        logger.info(f"Local results sufficient ({len(local_results)} results, max_score={(max((r.get('score', 0) for r in local_results), default=0)):.3f}), skipping web search")
        return False
