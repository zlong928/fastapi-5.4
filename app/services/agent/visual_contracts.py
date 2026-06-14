from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VisualExtractionContract:
    key: str
    role: str
    schema_template: str
    requirements: tuple[str, ...]
    csv_fields: tuple[str, ...] = ()

    def render(self, route_key: str) -> str:
        requirements = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(self.requirements))
        schema = self.schema_template.format(route_key=route_key)
        return f"""{self.role}当前处理链路：{route_key}。输出JSON：
{schema}

关键要求：
{requirements}"""


VISUAL_EXTRACTION_CONTRACTS: dict[str, VisualExtractionContract] = {
    "coordinate": VisualExtractionContract(
        key="coordinate",
        role="你是坐标数据提取专家。从图表中提取所有数据点坐标。",
        schema_template="""{{
  "figure": "图号",
  "chart_type": "{route_key}",
  "panels": [
    {{
      "panel": "子图编号（如A/B/left/right）",
      "source_page": "页码",
      "x_axis": {{"label": "X轴标签", "unit": "单位", "type": "linear/log/time_series/spectrum_frequency"}},
      "y_axis": {{"label": "Y轴标签", "unit": "单位", "type": "linear/log"}},
      "has_dual_y_axis": false,
      "right_y_axis": null,
      "phases": [
        {{"phase_name": "phase I/phase II/阶段名称", "x_start": 数值或null, "x_end": 数值或null, "boundary_note": "阶段边界说明"}}
      ],
      "series": [
        {{
          "series_name": "数据系列名称",
          "color": "颜色",
          "marker": "标记类型",
          "data_points": [
            {{"x": 数值, "y": 数值, "phase": "所属阶段或null", "y_error": 误差值或null}},
            {{"x": 数值, "y": 数值, "phase": "所属阶段或null", "y_error": 误差值或null}}
          ]
        }}
      ],
      "extraction_method": "vector/image_digitization",
      "notes": "备注信息"
    }}
  ]
}}""",
        requirements=(
            "提取图中每个可见数据点的x、y坐标",
            "区分不同数据系列（按颜色、标记）",
            "识别坐标轴类型（线性/对数）",
            "识别是否有双y轴",
            "如果是双相/分阶段时序图，必须提取 phases，并把每个点绑定到 phase",
            "如果是多曲线图，必须用 legend 将 series_name 与颜色/marker 绑定",
            "如果是带误差棒统计图，必须尽量读取 y_error、mean±SD、显著性标记",
            "如果是光谱/谱图，x_axis.type 使用 spectrum_frequency，并保留峰位、峰强或趋势",
            "所有可量化数值必须是数字，不要用字符串",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "series_name",
            "x_value",
            "y_value",
            "x_axis_label",
            "x_axis_unit",
            "x_axis_type",
            "y_axis_label",
            "y_axis_unit",
            "y_axis_type",
            "y_right_value",
            "y_right_axis_type",
            "legend_label",
            "legend_binding_status",
            "errorbar_height_px",
            "extraction_method",
            "axis_calibration_method",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
    "bar_chart": VisualExtractionContract(
        key="bar_chart",
        role="你是条形图/柱状图数据提取专家。",
        schema_template="""{{
  "figure": "图号",
  "panel": "子图编号",
  "chart_type": "{route_key}",
  "x_axis": {{"label": "X轴标签", "categories": ["类别1", "类别2"]}},
  "y_axis": {{"label": "Y轴标签", "unit": "单位"}},
  "series": [
    {{
      "series_name": "数据系列名称",
      "bars": [
        {{"category": "类别1", "value": 数值, "error_bar": 误差值或null, "significance": "显著性标记或null"}}
      ]
    }}
  ],
  "extraction_method": "vector/raster_digitization/llm_assisted_reading",
  "confidence": 0.85,
  "notes": "备注"
}}""",
        requirements=(
            "识别每个柱形的高度并转换为数值",
            "提取误差线（error bar）的值",
            "区分分组柱状图的不同系列",
            "如有显著性标记（*, **, p值、字母分组），写入 bars 的 significance 字段或 notes",
            "所有数值必须是数字",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "series_name",
            "x_axis_label",
            "y_axis_label",
            "y_axis_unit",
            "category_index",
            "category_label",
            "category_binding_status",
            "bar_left_px",
            "bar_right_px",
            "bar_top_px",
            "bar_bottom_px",
            "bar_height_px",
            "errorbar_top_px",
            "errorbar_bottom_px",
            "errorbar_height_px",
            "bar_geometry_status",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
    "heatmap": VisualExtractionContract(
        key="heatmap",
        role="你是热图/二维颜色场数据提取专家。",
        schema_template="""{{
  "figure": "图号",
  "panel": "子图编号",
  "chart_type": "{route_key}",
  "x_axis": {{"label": "X轴标签", "values": ["列1", "列2"]}},
  "y_axis": {{"label": "Y轴标签", "categories": ["行1", "行2"]}},
  "matrix": [[0.5, 0.8], [0.3, 0.9]],
  "colorbar": {{"min": 0, "max": 1, "label": "colorbar标签", "unit": "单位或null"}},
  "extraction_method": "llm_assisted_reading",
  "confidence": 0.6,
  "notes": "Colorbar values approximate due to gradient"
}}""",
        requirements=(
            "提取热图的行列标签",
            "根据颜色估算矩阵数值（如无法精确读取，标注approximate）",
            "提取colorbar的范围、单位和含义",
            "如果是二维颜色场，导出网格化 rows/columns/matrix，不要当成散点图",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "x_coordinate",
            "y_coordinate",
            "z_value",
            "z_axis_label",
            "z_axis_unit",
            "z_axis_type",
            "colorbar_min_value",
            "colorbar_max_value",
            "colorbar_unit",
            "colorbar_binding_status",
            "pixel_x",
            "pixel_y",
            "extraction_method",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
    "table_image": VisualExtractionContract(
        key="table_image",
        role="你是表格图像OCR专家。",
        schema_template="""{{
  "figure": "图号",
  "panel": null,
  "chart_type": "{route_key}",
  "table_data": {{
    "headers": ["列1", "列2", "列3"],
    "rows": [
      ["A1", "85.3", "99.2"],
      ["A2", "90.1", "98.5"]
    ]
  }},
  "extraction_method": "llm_assisted_reading",
  "confidence": 0.7,
  "notes": "OCR quality high"
}}""",
        requirements=(
            "读取表格的所有单元格内容",
            "保留表头和数据行的分离",
            "保持单元格的相对位置关系",
        ),
        csv_fields=(),
    ),
    "non_data_visual": VisualExtractionContract(
        key="non_data_visual",
        role="你是非坐标图片分析专家，处理显微图、SEM、荧光图、EDS mapping、照片、示意图和结构渲染。",
        schema_template="""{{
  "figure": "图号",
  "panel": "子图编号",
  "chart_type": "{route_key}",
  "description": "详细的图像描述",
  "visible_elements": ["scale bar: 10 μm", "cracks", "particles"],
  "quantitative_observations": [
    {{"name": "孔径/面积/细胞计数/元素分布等", "value": 数值或null, "unit": "单位或null", "method": "scale_bar/visual_count/qualitative"}}
  ],
  "extraction_method": "descriptive",
  "unsupported_reason": "No numerical data to extract"
}}""",
        requirements=(
            "描述图像的主要内容和可见元素",
            "提取比例尺、标尺等元信息",
            "如果是 microscopy_quant，优先读取 scale bar，并提取面积、孔径、细胞计数、元素分布等可量化观察",
            "如果是 schematic_or_photo，通常不导出 CSV，只保留 caption 和可见结构说明",
        ),
        csv_fields=(
            "image_file",
            "image_type",
            "panel_id",
            "scale_bar_length_px",
            "scale_bar_value",
            "scale_bar_unit",
            "pixel_size",
            "physical_area_value",
            "physical_area_unit",
            "component_area_px",
            "extraction_method",
            "data_quality",
            "extraction_confidence",
            "needs_review",
            "review_reason",
        ),
    ),
}


def visual_extraction_prompt(contract_key: str, route_key: str) -> str:
    contract = VISUAL_EXTRACTION_CONTRACTS[contract_key]
    return contract.render(route_key)


def visual_contract_csv_fields(contract_key: str) -> tuple[str, ...]:
    return VISUAL_EXTRACTION_CONTRACTS[contract_key].csv_fields


def generic_visual_system_prompt() -> str:
    return """你是顶级科研图表数据提取专家。你的任务是从图片中提取所有可见的数据和信息，并用中文详细解释。

## 分析步骤：

### 第一步：识别图表类型和结构
- 图表类型：柱状图/折线图/散点图/显微镜图/流程图/结构示意图/表格/组合图/其他
- 坐标轴信息：X轴标签、单位、刻度值；Y轴标签、单位、刻度值
- 图例信息：所有系列的名称、颜色、标记符号
- 标题和注释：主标题、子标题、图中所有文字标注

### 第二步：提取所有数据点
- 柱状图：每个柱子的高度数值
- 折线图：每个数据点的X、Y坐标
- 散点图：每个点的位置
- 显微镜图/示意图：关键尺寸、标注的数值
- 表格：所有单元格的数据

如果数值清晰可读：记录精确数值。
如果数值模糊：估算范围，如“约50-60”。
如果无法读取：标注“数值不可读”，但描述大致位置和趋势。

### 第三步：提取文本标注
记录图中所有文字：数据标签、统计显著性标记、箭头说明、误差线数值、百分比、倍数关系。

### 第四步：总结关键发现
用中文总结最大值、最小值、组间对比、变化趋势、统计显著性和关键数据点。

## 输出JSON格式：
{
  "figure_type": "具体图表类型",
  "title": "图表标题（中文）",
  "axes": {
    "x_axis": {"label": "X轴标签（中文）", "unit": "单位", "visible_values": ["刻度1", "刻度2"]},
    "y_axis": {"label": "Y轴标签（中文）", "unit": "单位", "range": "范围（如0-100）"}
  },
  "legend": [
    {"name": "系列名（中文）", "color": "颜色描述", "marker": "标记类型"}
  ],
  "data_points": [
    {
      "series": "所属系列（中文）",
      "x": "X值或分类",
      "y": "Y值",
      "value_label": "数据标签",
      "error_bar": "误差值（如有）",
      "significance": "显著性标记（如有）"
    }
  ],
  "annotations": ["图中所有文字标注（中文）"],
  "statistics": {
    "max_value": {"value": 数值, "condition": "条件（中文）"},
    "min_value": {"value": 数值, "condition": "条件（中文）"},
    "comparisons": ["对比1：A比B高50%", "对比2：C显著低于D (p<0.05)"]
  },
  "overall_description": "完整的中文描述，包括图表展示了什么、主要数据点、关键趋势、重要对比",
  "extractions": [{
    "metric": "提取的指标名",
    "success": true,
    "data": {"具体数值字段": 数值},
    "qualitative": "用中文详细描述该指标的数值、趋势、对比关系",
    "confidence": "high/medium/low",
    "notes": "补充说明（中文）",
    "evidence": "图中可见的证据（坐标轴数值、标注文字等）"
  }],
  "key_findings": [
    "关键发现1：具体数值+单位+对比（中文）",
    "关键发现2：趋势+幅度+显著性（中文）"
  ],
  "extraction_completeness": "完整度评估（如：已提取所有可见数据点/部分数据点模糊）"
}

## 严格要求：
1. 全部中文：所有描述、标签、结论必须用中文。
2. 不遗漏数据：提取图中每一个可见的数据点。
3. 精确优先：能看清数值就记录精确数值，不要只说“较高”或“增加”。
4. 结构化：数据必须结构化存储在 data_points 数组中。
5. 可验证：所有结论必须基于图中可见证据。
6. 完整解释：key_findings 必须包含具体数值和单位。
7. 中文图例：如果图例是英文，翻译成中文。

如果无法稳定输出合法 JSON，也不要空响应；请直接输出一段中文证据描述。系统会使用同一次响应作为降级证据，禁止等待二次分析。"""


def generic_visual_user_prompt(figure_id: str, caption: str, tasks_desc: str, review_note: str = "") -> str:
    review = f"\n复核提示：{review_note}" if review_note else ""
    return f"""# 图表信息
- 图表编号：{figure_id}
- 图注：{caption}

# 提取任务
{tasks_desc}

# 分析要求
请严格按照系统提示的步骤，完整提取这个图表中的所有信息：

1. 完整识别结构：图表类型、坐标轴（标签+刻度值）、图例（所有系列）
2. 提取所有数据点：图中每个柱/点/线的具体数值，不要遗漏
3. 记录所有文字：标题、标签、数据标签、统计标记、注释
4. 总结关键发现：用中文说明主要数据、对比关系、显著性，必须包含具体数值

关键要求：
- 提取图中每一个可见的数据点
- 所有描述必须用中文
- 数值必须精确记录（能看清就记数值）
- 结论必须具体（如“A组85%，比B组60%高41.7%”，而不是“A组较高”）
{review}"""


def visual_text_fallback_prompt() -> str:
    return (
        "请用中文描述这张论文图或页面截图。只列出图中实际可见、可核验的正向信息："
        "可读数值、趋势、坐标轴、图例、文字标注、显著性标记、结构位置或形态。"
        "如果某类信息不存在，不要写“没有/无法提取/不包含”。不要输出 JSON，不要解释过程，控制在500字以内。"
    )
