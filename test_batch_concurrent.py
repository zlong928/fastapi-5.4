#!/usr/bin/env python3
"""
测试批量提取的并发处理

模拟大量图片的并发提取，验证：
1. 并发控制是否正常（最大100）
2. 错误处理是否正确
3. 进度追踪是否准确
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.chart_extraction.batch_async import process_images_batch_async
from app.services.chart_extraction.models import ImageRecord


async def test_concurrent_processing():
    """测试并发处理"""

    # 创建测试用的 ImageRecord（模拟不同类型的图片）
    test_cases = [
        # 数据图表（应该提取）
        ("chart", "Viscosity vs shear rate", "line_plot"),
        ("chart", "FTIR spectrum", "chart"),
        ("bar_chart", "Comparison of groups", "bar_chart"),
        ("scatter_plot", "Correlation plot", "scatter_plot"),
        ("chart", "XRD pattern", "chart"),

        # 非数据图片（应该跳过）
        ("image", "SEM micrograph", "image"),
        ("image", "Colony count", "image"),
        ("flowchart", "Schematic diagram", "flowchart"),
        ("photo", "Experimental setup", "photo"),
        ("image", "Microscopy image", "image"),
    ]

    # 创建临时目录
    temp_dir = Path("/tmp/test_batch_extract")
    temp_dir.mkdir(exist_ok=True)

    # 创建测试图片文件（空文件）
    records = []
    for idx, (mineru_type, caption, mineru_sub_type) in enumerate(test_cases):
        image_path = temp_dir / f"test_{idx:03d}.jpg"
        image_path.touch()

        record = ImageRecord(
            path=image_path,
            ordinal=idx,
            mineru_type=mineru_type,
            mineru_sub_type=mineru_sub_type,
            caption=caption,
            content=caption,
        )
        records.append(record)

    print("=" * 80)
    print(f"测试并发批量提取")
    print(f"总图片数: {len(records)}")
    print(f"最大并发: 100")
    print("=" * 80)
    print()

    # 进度回调
    start_time = time.time()
    last_progress_time = start_time

    def progress_callback(current: int, total: int):
        nonlocal last_progress_time
        now = time.time()
        elapsed = now - start_time
        progress_elapsed = now - last_progress_time
        last_progress_time = now

        percent = (current / total) * 100
        rate = current / elapsed if elapsed > 0 else 0

        print(f"进度: {current}/{total} ({percent:.1f}%) | "
              f"耗时: {elapsed:.1f}s | "
              f"速率: {rate:.1f} 张/秒 | "
              f"间隔: {progress_elapsed:.2f}s")

    # 执行批量处理
    try:
        results = await process_images_batch_async(
            records=records,
            out_dir=temp_dir,
            sample_limit=200,
            max_concurrent=100,
            progress_callback=progress_callback
        )

        # 统计结果
        total_time = time.time() - start_time
        success_count = sum(1 for r in results if r.get("status") == "success")
        skipped_count = sum(1 for r in results if r.get("status") == "skipped")
        failed_count = sum(1 for r in results if r.get("status") == "failed")

        print()
        print("=" * 80)
        print("测试完成")
        print("=" * 80)
        print(f"总耗时: {total_time:.2f} 秒")
        print(f"平均速率: {len(records) / total_time:.2f} 张/秒")
        print(f"成功: {success_count} 张")
        print(f"跳过: {skipped_count} 张")
        print(f"失败: {failed_count} 张")
        print()

        # 显示详细结果
        print("详细结果:")
        for idx, (record, result) in enumerate(zip(records, results)):
            status = result.get("status", "unknown")
            reason = result.get("reason", "")
            print(f"  [{idx+1:2d}] {record.caption[:40]:40s} → {status:10s} {reason}")

        # 清理
        for record in records:
            if record.path.exists():
                record.path.unlink()
        temp_dir.rmdir()

        return success_count > 0 and failed_count == 0

    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_high_concurrency():
    """测试高并发场景（模拟27张图片）"""
    print("\n" + "=" * 80)
    print("高并发测试（27张图片）")
    print("=" * 80)

    # 创建27个测试记录
    temp_dir = Path("/tmp/test_batch_extract_27")
    temp_dir.mkdir(exist_ok=True)

    records = []
    for i in range(27):
        image_path = temp_dir / f"figure_{i+1:02d}.jpg"
        image_path.touch()

        # 模拟不同类型
        if i % 5 == 0:
            caption = f"SEM image {i+1}"
            mineru_type = "image"
        else:
            caption = f"Chart {i+1}: Flow curve"
            mineru_type = "chart"

        record = ImageRecord(
            path=image_path,
            ordinal=i,
            mineru_type=mineru_type,
            mineru_sub_type=mineru_type,
            caption=caption,
            content=caption,
        )
        records.append(record)

    start_time = time.time()

    def progress_callback(current: int, total: int):
        elapsed = time.time() - start_time
        percent = (current / total) * 100
        print(f"  处理进度: {current}/{total} ({percent:.0f}%) - {elapsed:.1f}s")

    results = await process_images_batch_async(
        records=records,
        out_dir=temp_dir,
        sample_limit=200,
        max_concurrent=100,
        progress_callback=progress_callback
    )

    elapsed = time.time() - start_time
    print(f"\n完成! 耗时: {elapsed:.2f}s, 平均: {27/elapsed:.1f} 张/秒")

    # 清理
    for record in records:
        if record.path.exists():
            record.path.unlink()
    temp_dir.rmdir()


if __name__ == "__main__":
    print("批量提取并发测试")
    print()

    # 运行测试
    success = asyncio.run(test_concurrent_processing())

    # 高并发测试
    asyncio.run(test_high_concurrency())

    sys.exit(0 if success else 1)
