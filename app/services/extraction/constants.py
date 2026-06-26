EXTRACTION_PHASE_EVENT = "extraction_phase"

PHASE_LABELS = {
    "PENDING": "等待开始",
    "PLANNING": "规划任务",
    "MAPPING": "映射全文",
    "REFLECTION": "复核映射",
    "VISUAL_ANALYSIS": "视觉分析",
    "AGGREGATION": "汇总结果",
    "RESULT_REFLECTION": "结果复核",
    "FINISH": "完成",
    "CLASSIFYING": "LLM 规划指标",
    "ROUTING": "检索证据",
    "EXTRACTING_SECTIONS": "提取正文内容",
    "EXTRACTING_FIGURES": "提取图表内容",
    "EXTRACTING_TEXT": "补充正文检索",
    "FUSING": "融合复核",
    "DONE": "完成",
    "FAILED": "失败",
}

PHASE_BASE_PERCENT = {
    "PENDING": 0,
    "PLANNING": 10,
    "MAPPING": 25,
    "REFLECTION": 40,
    "VISUAL_ANALYSIS": 45,
    "AGGREGATION": 85,
    "RESULT_REFLECTION": 95,
    "FINISH": 100,
    "CLASSIFYING": 10,
    "ROUTING": 25,
    "EXTRACTING_SECTIONS": 45,
    "EXTRACTING_FIGURES": 65,
    "EXTRACTING_TEXT": 75,
    "FUSING": 90,
    "DONE": 100,
    "FAILED": 0,
}

NEGATIVE_RESULT_MARKERS = (
    "没有任何",
    "没有可",
    "不包含可",
    "无法提取",
    "不能提取",
    "不可读取",
    "无法读取",
    "没有坐标轴",
    "没有可见比例尺",
    "没有可直接读取",
    "不存在可",
    "无可提取",
)

GENERIC_RESULT_FIELDS = {
    "materials_methods",
    "materials",
    "key_metrics",
    "figure_data",
    "visible_evidence",
    "comprehensive_data_extraction",
}
