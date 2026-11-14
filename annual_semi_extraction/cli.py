"""CLI 入口：薄层，仅解析参数、调用包模块。

遵循 CLI → Task → Units 模式（Pattern 1: CLI-driven Application）。
当前阶段 CLI 直接调用包模块；当出现第二个调用源时再抽取 Task 层。
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from annual_semi_extraction.config import LOG_LEVEL
from annual_semi_extraction.h1.extractor import extract, extract_batch
from annual_semi_extraction.e1.judge import E1Judge
from annual_semi_extraction.spec.loader import SpecLoader
from annual_semi_extraction.rustfs import get_client

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(help="A 股年报/半年报 MD 内容抽取与特征矩阵生产。")


@app.command()
def h1_extract(
    input_dir: Path = typer.Option(
        Path("data/md_cache/published"),
        "--input-dir", "-i",
        help="输入目录（本地缓存的 MD 文件根目录，将递归扫描）。"
             "默认 data/md_cache/published（RustFS 本地镜像）。"
             "若目录为空，需先运行 scripts/fetch_all_md.py 从 RustFS 同步。",
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    output: Path = typer.Option(
        Path("data/h1_extraction.jsonl"),
        "--output", "-o",
        help="输出 JSONL 文件路径",
    ),
    failures: Path = typer.Option(
        Path("data/h1_extraction_failures.jsonl"),
        "--failures", "-f",
        help="失败/残差记录输出路径",
    ),
    limit: int = typer.Option(
        0,
        "--limit", "-l",
        help="限制处理文件数（0=不限制，调试用）",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        help="跳过前 N 个文件（断点续传用）",
    ),
    append: bool = typer.Option(
        False,
        "--append", "-a",
        help="追加模式（不覆盖已有文件）",
    ),
    no_frozen: bool = typer.Option(
        False,
        "--no-frozen",
        help="跳过冻结组合库判定",
    ),
):
    """H1 标题全量抽取：扫描 input_dir 下所有 MD 文件，抽取 H1 标题并写入 JSONL。

    数据来源：MD 文件存储在 RustFS（s3.rustfs.pro.neuralj.com），本命令读取本地缓存
    （默认 data/md_cache/published）。若缓存为空，需先运行：
        python scripts/fetch_all_md.py

    输出：每行一个 JSON 对象，包含 slot_key、headings、extraction_method 等字段。
    """
    logger.info(f"H1 抽取: input={input_dir}, output={output}")
    result = extract_batch(input_dir, output, failures,
                           limit=limit, offset=offset,
                           append=append, no_frozen=no_frozen)
    n_ok = result["n_ok"]
    n_files = result["n_files"]
    complete = result["complete"]
    residual = result["residual"]
    logger.info(f"完成: {n_ok}/{n_files} 份, "
                f"完整 L1: {complete} ({complete/max(1,n_ok):.1%}), "
                f"残差: {residual}")
    typer.echo(f"-> {output}")


@app.command()
def h1_extract_single(
    md_path: Path = typer.Argument(..., help="单个 MD 文件路径", exists=True),
):
    """H1 标题单文件抽取（调试用）：输出 JSON 到 stdout。"""
    rec = extract(md_path)
    if rec is None:
        typer.echo("无有效 H1 标题", err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(rec, ensure_ascii=False, indent=2))


@app.command()
def e1_spec(
    year: int = typer.Option(..., "--year", "-y", help="报告年份"),
    period: int = typer.Option(..., "--period", "-p", help="报告期（1=一季报, 2=半年报, 3=三季报, 4=年报）"),
):
    """E1 规格查询：打印指定年份/报告期的法定应披章节。"""
    spec = SpecLoader()
    chapters = spec.get_required_chapters(year, period)
    typer.echo(f"{year}_{period} 应披章节 ({len(chapters)} 个):")
    for ch in chapters:
        typer.echo(f"  - {ch}")


@app.command()
def rustfs_read(
    key: str = typer.Argument(
        ...,
        help="RustFS 对象路径，如 'published/000001/000001_2024_4.md'",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="输出文件路径（不指定则输出到 stdout）",
    ),
    head: Optional[int] = typer.Option(
        None,
        "--head", "-n",
        help="只输出前 N 行（调试用）",
    ),
    h1_extract: bool = typer.Option(
        False,
        "--h1",
        help="识别一级章节标题（H1）并输出抽取结果",
    ),
):
    """从 RustFS 读取 MD 文件，可选识别一级标题。

    数据来源：RustFS 对象存储（s3.rustfs.pro.neuralj.com），局域网部署，延迟 ~17ms。

    示例：
        # 输出原始内容到终端
        nooshare-annual-semi-extraction rustfs-read published/000001/000001_2024_4.md

        # 识别一级标题
        nooshare-annual-semi-extraction rustfs-read published/000001/000001_2024_4.md --h1

        # 保存到本地
        nooshare-annual-semi-extraction rustfs-read published/000001/000001_2024_4.md -o local.md

        # 只看前 50 行
        nooshare-annual-semi-extraction rustfs-read published/000001/000001_2024_4.md --head 50
    """
    import tempfile
    client = get_client()
    try:
        content = client.read_text(key)
    except FileNotFoundError:
        typer.echo(f"错误：对象不存在 {key}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"错误：读取失败 {type(e).__name__}: {e}", err=True)
        raise typer.Exit(code=1)

    # H1 识别模式
    if h1_extract:
        # 从 key 提取文件名（如 published/000001/000001_2024_4.md -> 000001_2024_4.md）
        filename = key.rsplit("/", 1)[-1]
        # 写入临时目录，但保持文件名格式供 slot_key_from_path() 识别
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_path = tmp_dir / filename
        try:
            tmp_path.write_text(content, encoding="utf-8")
            result = extract(tmp_path)
            if result is None:
                typer.echo("无有效 H1 标题", err=True)
                raise typer.Exit(code=1)
            # 输出 JSON 结果
            output_text = json.dumps(result, ensure_ascii=False, indent=2)
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(output_text, encoding="utf-8")
                typer.echo(f"-> {output}")
            else:
                typer.echo(output_text)
        finally:
            tmp_path.unlink(missing_ok=True)
            tmp_dir.rmdir()
        return

    # 原始内容模式
    if head:
        lines = content.splitlines(keepends=True)[:head]
        content = "".join(lines)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        typer.echo(f"-> {output} ({len(content)} bytes)")
    else:
        typer.echo(content)


@app.command()
def rustfs_list(
    prefix: str = typer.Argument(
        ...,
        help="前缀路径，如 'published/000001/'",
    ),
    limit: int = typer.Option(
        100,
        "--limit", "-l",
        help="最大返回数量（默认 100）",
    ),
):
    """列出 RustFS 上指定前缀的对象。

    示例：
        # 列出 000001 的所有报告
        nooshare-annual-semi-extraction rustfs-list published/000001/

        # 限制数量
        nooshare-annual-semi-extraction rustfs-list published/ --limit 20
    """
    import boto3
    from botocore.config import Config
    from annual_semi_extraction.rustfs import ENDPOINT_URL, ACCESS_KEY, SECRET_KEY, BUCKET

    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    )
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        verify=False,
        config=config,
    )

    try:
        response = client.list_objects_v2(
            Bucket=BUCKET,
            Prefix=prefix,
            MaxKeys=limit,
        )
        objects = response.get("Contents", [])
        if not objects:
            typer.echo(f"无对象匹配前缀：{prefix}")
            return

        typer.echo(f"前缀 {prefix} 下共 {len(objects)} 个对象：")
        for obj in objects:
            size_kb = obj["Size"] / 1024
            typer.echo(f"  {obj['Key']}  ({size_kb:.1f} KB)")
    except Exception as e:
        typer.echo(f"错误：列出失败 {type(e).__name__}: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def rustfs_combo(
    output: Path = typer.Option(
        Path("data/h1_combo_library.json"),
        "--output", "-o",
        help="输出 JSON 文件路径（去重后的组合库）",
    ),
    prefix: str = typer.Option(
        "published/",
        "--prefix", "-p",
        help="RustFS 对象前缀（默认 published/）",
    ),
    limit: int = typer.Option(
        0,
        "--limit", "-l",
        help="限制处理文件数（0=不限制，调试用）",
    ),
    min_count: int = typer.Option(
        2,
        "--min-count",
        help="最少出现次数才纳入组合库（默认 2）",
    ),
):
    """从 RustFS 全量抽取 H1 标题，生成去重组合库。

    流程：
    1. 分页列出 RustFS 上所有 MD 文件（默认 published/ 前缀）
    2. 逐个下载并抽取 H1 标题
    3. 按标题模式（canonical_cat 序列）去重
    4. 输出每种组合的出现次数、代表样本、覆盖率统计

    示例：
        # 全量生成（约 37k 文件，预计 10-15 分钟）
        nooshare-annual-semi-extraction rustfs-combo

        # 调试模式：只处理前 100 个文件
        nooshare-annual-semi-extraction rustfs-combo --limit 100

        # 调整最小出现次数
        nooshare-annual-semi-extraction rustfs-combo --min-count 5
    """
    import tempfile
    from collections import Counter, defaultdict
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher

    client = get_client()
    matcher = get_pattern_matcher()
    n_library_matched = 0  # 命中标准库、跳过的文件数

    # 1. 列出所有 MD 文件
    typer.echo(f"列出 RustFS 对象（前缀 {prefix}）...")
    try:
        all_objects = client.list_objects(prefix=prefix)
    except Exception as e:
        typer.echo(f"错误：列出对象失败 {type(e).__name__}: {e}", err=True)
        raise typer.Exit(code=1)

    md_objects = [obj for obj in all_objects if obj["key"].endswith(".md")]
    typer.echo(f"共 {len(md_objects)} 个 MD 文件")

    if limit > 0:
        md_objects = md_objects[:limit]
        typer.echo(f"限制处理前 {limit} 个")

    # 2. 逐个抽取 H1
    combo_counter: Counter = Counter()  # pattern_tuple -> count
    combo_samples: dict = defaultdict(list)  # pattern_tuple -> [slot_key, ...]
    combo_headings: dict = {}  # pattern_tuple -> headings list
    combo_coverage: dict = {}  # pattern_tuple -> coverage info

    n_ok = 0
    n_fail = 0
    tmp_dir = Path(tempfile.mkdtemp())

    try:
        for i, obj in enumerate(md_objects, start=1):
            key = obj["key"]
            filename = key.rsplit("/", 1)[-1]

            try:
                # 下载并抽取
                content = client.read_text(key)
                tmp_path = tmp_dir / filename
                tmp_path.write_text(content, encoding="utf-8")

                rec = extract(tmp_path)
                tmp_path.unlink(missing_ok=True)

                if rec is None:
                    n_fail += 1
                    continue

                # 构建模式键：raw_name 序列（原始标题文本）
                headings = rec.get("headings", [])
                if not headings:
                    n_fail += 1
                    continue

                pattern = tuple(
                    h.get("raw_name", "")
                    for h in headings
                    if h.get("raw_name", "")
                )

                # 如果过滤后为空，跳过
                if not pattern:
                    n_fail += 1
                    continue

                # 标准库匹配：命中则跳过，不纳入组合库统计
                if matcher.match(list(pattern)):
                    n_library_matched += 1
                    continue

                combo_counter[pattern] += 1
                if len(combo_samples[pattern]) < 5:  # 只保留前 5 个样本
                    combo_samples[pattern].append(rec["slot_key"])
                if pattern not in combo_headings:
                    combo_headings[pattern] = headings
                if pattern not in combo_coverage:
                    combo_coverage[pattern] = {
                        "is_complete_l1": rec.get("is_complete_l1", False),
                        "coverage_ratio": rec.get("coverage_ratio", 0.0),
                        "extraction_method": rec.get("extraction_method", "unknown"),
                    }

                n_ok += 1

            except Exception as e:
                n_fail += 1
                logger.debug(f"处理失败 {key}: {type(e).__name__}: {e}")

            if i % 1000 == 0:
                typer.echo(f"  进度: {i}/{len(md_objects)}, 成功 {n_ok}, 失败 {n_fail}, "
                          f"唯一组合 {len(combo_counter)}")

    finally:
        tmp_dir.rmdir()

    # 3. 过滤并输出
    typer.echo(f"\n抽取完成: {n_ok} 成功, {n_fail} 失败, {len(combo_counter)} 唯一组合")

    # 按出现次数排序，过滤最小次数
    filtered_combos = [
        (pattern, count)
        for pattern, count in combo_counter.most_common()
        if count >= min_count
    ]

    typer.echo(f"出现次数 >= {min_count} 的组合: {len(filtered_combos)}")

    # 构建输出
    output_data = {
        "metadata": {
            "total_files": len(md_objects),
            "processed_ok": n_ok,
            "processed_fail": n_fail,
            "unique_combos_total": len(combo_counter),
            "unique_combos_filtered": len(filtered_combos),
            "min_count_threshold": min_count,
        },
        "combos": [
            {
                "pattern": list(pattern),
                "n_headings": len(pattern),
                "count": count,
                "samples": combo_samples[pattern],
                "headings": combo_headings[pattern],
                "coverage": combo_coverage[pattern],
            }
            for pattern, count in filtered_combos
        ],
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    typer.echo(f"-> {output}")

    # 打印 Top 10
    typer.echo("\nTop 10 组合:")
    for i, (pattern, count) in enumerate(filtered_combos[:10], start=1):
        typer.echo(f"  {i}. 出现 {count} 次, {len(pattern)} 个标题: "
                  f"{', '.join(pattern[:5])}{'...' if len(pattern) > 5 else ''}")


@app.command()
def version():
    """打印版本号。"""
    from annual_semi_extraction import __version__
    typer.echo(f"nooshare-annual-semi-extraction {__version__}")


if __name__ == "__main__":
    app()
