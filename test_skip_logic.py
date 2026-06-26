#!/usr/bin/env python3
"""
测试批量提取的跳过逻辑
验证哪些图片会被跳过，哪些会被提取
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.chart_extraction.image_routing import skip_reason
from app.services.chart_extraction.models import ImageRecord
import numpy as np


def test_skip_logic():
    """测试各种图片类型的跳过逻辑"""

    # 测试用例：(mineru_sub_type, caption, 期望结果)
    test_cases = [
        # 应该跳过的图片
        ("flowchart", "Schematic diagram of the process", "应该跳过"),
        ("photo", "Photo of the experimental setup", "应该跳过"),
        ("natural_image", "Image of bacterial colonies", "应该跳过"),
        ("image", "SEM micrograph of the surface", "应该跳过"),
        ("image", "TEM image showing cell morphology", "应该跳过"),
        ("image", "Confocal microscopy image", "应该跳过"),
        ("image", "Colony count on agar plate", "应该跳过"),
        ("image", "Bacterial growth on petri dish", "应该跳过"),
        ("image", "Cell morphology under microscope", "应该跳过"),
        ("image", "Surface morphology by SEM", "应该跳过"),
        ("image", "Cross-section of the material", "应该跳过"),

        # 应该提取的图片
        ("line_plot", "Viscosity vs shear rate", "应该提取"),
        ("chart", "Flow curve showing viscosity", "应该提取"),
        ("bar_chart", "Comparison of different groups", "应该提取"),
        ("scatter_plot", "Correlation between X and Y", "应该提取"),
        ("chart", "FTIR spectrum of the sample", "应该提取"),
        ("chart", "XRD pattern", "应该提取"),
        ("line_plot", "Time series of temperature", "应该提取"),
        ("chart", "Storage modulus G' vs strain", "应该提取"),
        ("heatmap", "Heatmap showing expression levels", "应该提取"),
    ]

    print("=" * 80)
    print("测试批量提取跳过逻辑")
    print("=" * 80)
    print()

    passed = 0
    failed = 0

    for mineru_sub_type, caption, expected in test_cases:
        # 创建测试用的ImageRecord
        record = ImageRecord(
            path=Path("test.jpg"),
            ordinal=1,
            mineru_type="figure",
            mineru_sub_type=mineru_sub_type,
            caption=caption,  # 使用 caption 而不是 content
            content=caption,  # 也设置 content 以保持一致
        )

        # 创建测试用的图片（800x600）
        test_image = np.zeros((600, 800, 3), dtype=np.uint8)

        # 调用skip_reason
        reason = skip_reason(record, test_image)

        # 判断结果
        should_skip = "跳过" in expected
        actually_skipped = reason is not None

        if should_skip == actually_skipped:
            status = "✓ 通过"
            passed += 1
        else:
            status = "✗ 失败"
            failed += 1

        print(f"{status}")
        print(f"  类型: {mineru_sub_type}")
        print(f"  标题: {caption}")
        print(f"  期望: {expected}")
        print(f"  实际: {'跳过' if actually_skipped else '提取'} ({reason if reason else 'None'})")
        print()

    print("=" * 80)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 80)

    return failed == 0


if __name__ == "__main__":
    success = test_skip_logic()
    sys.exit(0 if success else 1)
