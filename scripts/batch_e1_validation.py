import os\n"""批量 E1 验证脚本。

对 2021-2024 年全部年报/半年报运行 E1 章节完备性判定。
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 添加上游项目路径（用于访问 annual_semi.db）
UPSTREAM_PROJECT = Path(r"C:\dev\nooshare-annual-semi")
sys.path.insert(0, str(UPSTREAM_PROJECT))

from annual_semi_extraction.spec_loader import SpecLoader
from annual_semi_extraction.e1_judge import E1Judge
from annual_semi_extraction.chapter_extractor import extract_chapters_from_md

# 铁律 4：槽位主键复用上游公共类型，禁止各写各的 f-string
from annual_semi.completeness import slot_key


def get_report_list_from_db() -> list[dict]:
    """从数据库获取 2021-2024 年报告列表。
    
    Returns:
        [{"stock_code": "000001", "year": 2021, "period": 4, "md_path": "published/000001/000001_2021_4.md"}, ...]
    """
    try:
        # 导入上游项目的数据库模块
        from annual_semi.db._conn import connect
        conn = connect()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT stock_code, report_year, period, winner_md_path
            FROM annual_semi.reconciled_report
            WHERE period IN (2, 4)
              AND report_year BETWEEN 2021 AND 2024
            ORDER BY report_year, period, stock_code
        """)
        
        reports = []
        for row in cur.fetchall():
            reports.append({
                "stock_code": row[0],
                "year": row[1],
                "period": row[2],
                "md_path": row[3],  # winner_md_path
            })
        
        conn.close()
        return reports
    except ImportError:
        print("无法导入上游项目数据库模块", file=sys.stderr)
        print("请确保上游项目路径正确：C:\\dev\\nooshare-annual-semi", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"从数据库获取报告列表失败: {e}", file=sys.stderr)
        print("请确保已配置 PostgreSQL 连接", file=sys.stderr)
        sys.exit(1)


def download_md_from_rustfs(md_path: str, local_dir: Path) -> Optional[Path]:
    """从 RustFS 下载 MD 文件。
    
    Args:
        md_path: RustFS 中的路径，如 "published/000001/000001_2021_4.md"
        local_dir: 本地缓存目录
    
    Returns:
        本地文件路径，或 None（下载失败）
    """
    import boto3
    from botocore.config import Config
    
    # RustFS 配置
    ENDPOINT_URL = "https://s3.rustfs.pro.neuralj.com"
    ACCESS_KEY = os.environ.get("RUSTFS_ACCESS_KEY", "")
    SECRET_KEY = os.environ.get("RUSTFS_SECRET_KEY", "")
    BUCKET = "annual-semi"
    
    # 构建本地路径
    local_path = local_dir / md_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 如果已存在，直接返回
    if local_path.exists():
        return local_path
    
    try:
        config = Config(signature_version='s3v4', s3={'addressing_style': 'path'})
        client = boto3.client(
            's3',
            endpoint_url=ENDPOINT_URL,
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            verify=False,
            config=config,
        )
        
        client.download_file(BUCKET, md_path, str(local_path))
        return local_path
    except Exception as e:
        print(f"下载失败 {md_path}: {e}", file=sys.stderr)
        return None


def validate_single_report(
    judge: E1Judge,
    stock_code: str,
    year: int,
    period: int,
    md_text: str,
) -> dict:
    """验证单份报告。
    
    Returns:
        {
            "stock_code": "000001",
            "year": 2021,
            "period": 4,
            "is_compliant": True,
            "compliance_rate": 1.0,
            "missing": [],
            "extra": [],
            "error": None,
        }
    """
    report_id = slot_key(stock_code, year, period)
    
    try:
        # 提取章节
        disclosed_chapters = extract_chapters_from_md(md_text)
        
        # 判定
        result = judge.judge(
            report_id=report_id,
            period=period,
            report_year=year,
            disclosed_chapters=disclosed_chapters,
        )
        
        return {
            "stock_code": stock_code,
            "year": year,
            "period": period,
            "is_compliant": result.is_compliant,
            "compliance_rate": result.compliance_rate,
            "missing": result.missing,
            "extra": result.extra_chapters,
            "order_violations": result.order_violations,
            "error": None,
        }
    except Exception as e:
        return {
            "stock_code": stock_code,
            "year": year,
            "period": period,
            "is_compliant": False,
            "compliance_rate": 0.0,
            "missing": [],
            "extra": [],
            "order_violations": [],
            "error": str(e),
        }


def main():
    """主函数。"""
    import argparse
    
    parser = argparse.ArgumentParser(description="批量 E1 验证")
    parser.add_argument("--limit", type=int, help="限制验证数量（调试用）")
    parser.add_argument("--output", type=str, default="e1_validation_report.json", help="输出文件路径")
    parser.add_argument("--cache-dir", type=str, default="data/md_cache", help="MD 文件缓存目录")
    args = parser.parse_args()
    
    # 初始化
    spec_dir = Path(__file__).parent.parent / "annual_semi_extraction" / "spec"
    loader = SpecLoader(spec_dir)
    judge = E1Judge(loader)
    
    # 获取报告列表
    print("从数据库获取报告列表...")
    reports = get_report_list_from_db()
    print(f"共 {len(reports)} 份报告")
    
    if args.limit:
        reports = reports[:args.limit]
        print(f"限制验证前 {len(reports)} 份")
    
    # 准备缓存目录
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # 批量验证
    results = []
    stats = {
        "total": len(reports),
        "compliant": 0,
        "non_compliant": 0,
        "error": 0,
        "by_year_period": defaultdict(lambda: {"total": 0, "compliant": 0, "error": 0}),
        "missing_chapters": defaultdict(int),
        "extra_chapters": defaultdict(int),
    }
    
    for i, report in enumerate(reports):
        if (i + 1) % 100 == 0:
            print(f"进度: {i + 1}/{len(reports)}")
        
        # 下载 MD 文件
        md_path = download_md_from_rustfs(report["md_path"], cache_dir)
        if md_path is None:
            stats["error"] += 1
            stats["by_year_period"][f"{report['year']}_P{report['period']}"]["error"] += 1
            results.append({
                "stock_code": report["stock_code"],
                "year": report["year"],
                "period": report["period"],
                "is_compliant": False,
                "compliance_rate": 0.0,
                "missing": [],
                "extra": [],
                "order_violations": [],
                "error": "下载失败",
            })
            continue
        
        # 读取 MD 文本
        try:
            md_text = md_path.read_text(encoding='utf-8')
        except Exception as e:
            stats["error"] += 1
            stats["by_year_period"][f"{report['year']}_P{report['period']}"]["error"] += 1
            results.append({
                "stock_code": report["stock_code"],
                "year": report["year"],
                "period": report["period"],
                "is_compliant": False,
                "compliance_rate": 0.0,
                "missing": [],
                "extra": [],
                "order_violations": [],
                "error": f"读取失败: {e}",
            })
            continue
        
        # 验证
        result = validate_single_report(
            judge,
            report["stock_code"],
            report["year"],
            report["period"],
            md_text,
        )
        results.append(result)
        
        # 更新统计
        yp_key = f"{report['year']}_P{report['period']}"
        stats["by_year_period"][yp_key]["total"] += 1
        
        if result["error"]:
            stats["error"] += 1
            stats["by_year_period"][yp_key]["error"] += 1
        elif result["is_compliant"]:
            stats["compliant"] += 1
            stats["by_year_period"][yp_key]["compliant"] += 1
        else:
            stats["non_compliant"] += 1
        
        # 统计缺失章节
        for chapter in result["missing"]:
            stats["missing_chapters"][chapter] += 1
        
        # 统计多余章节
        for chapter in result["extra"]:
            stats["extra_chapters"][chapter] += 1
    
    # 输出报告
    output = {
        "stats": {
            "total": stats["total"],
            "compliant": stats["compliant"],
            "non_compliant": stats["non_compliant"],
            "error": stats["error"],
            "compliance_rate": stats["compliant"] / stats["total"] if stats["total"] > 0 else 0.0,
            "by_year_period": dict(stats["by_year_period"]),
            "missing_chapters": dict(stats["missing_chapters"]),
            "extra_chapters": dict(stats["extra_chapters"]),
        },
        "results": results,
    }
    
    output_path = Path(args.output)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # 打印摘要
    print("\n" + "=" * 60)
    print("E1 验证报告摘要")
    print("=" * 60)
    print(f"总报告数: {stats['total']}")
    print(f"合规: {stats['compliant']} ({stats['compliant'] / stats['total'] * 100:.1f}%)")
    print(f"不合规: {stats['non_compliant']} ({stats['non_compliant'] / stats['total'] * 100:.1f}%)")
    print(f"错误: {stats['error']} ({stats['error'] / stats['total'] * 100:.1f}%)")
    print(f"\n按年份/期间:")
    for yp, s in sorted(stats["by_year_period"].items()):
        rate = s["compliant"] / s["total"] * 100 if s["total"] > 0 else 0
        print(f"  {yp}: {s['total']} 份, 合规 {s['compliant']} ({rate:.1f}%), 错误 {s['error']}")
    
    if stats["missing_chapters"]:
        print(f"\n最常缺失章节 (Top 5):")
        for chapter, count in sorted(stats["missing_chapters"].items(), key=lambda x: -x[1])[:5]:
            print(f"  {chapter}: {count} 次")
    
    print(f"\n完整报告已保存至: {output_path}")


if __name__ == "__main__":
    main()
