"""CLI 入口：薄层，仅解析参数、调用包模块。

遵循 CLI → Task → Units 模式（Pattern 1: CLI-driven Application）。
当前阶段 CLI 直接调用包模块；当出现第二个调用源时再抽取 Task 层。
"""

import json
import logging
import sys
import tempfile
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


# ── rustfs-combo 多进程 worker ────────────────────────────────────────
# 必须是模块顶层函数：Python 3.14 在 Linux 默认 forkserver、在 Windows 用
# spawn，二者都靠 pickle 传递函数引用，嵌套函数无法序列化。
# 每个进程持有独立的 RustFS 连接与 PG 连接，绝不继承父进程句柄。
_COMBO_STATE: dict = {}


def _combo_worker_init(endpoint: str | None, tmp_root: str) -> None:
    """子进程初始化（每个进程只跑一次）。

    只建 RustFS 连接。标准库判定由 extract() 内部完成并写进
    rec["library_match"]，worker 直接复用，因此子进程不需要再连 PG，
    也避免 forkserver 下 psycopg2 连接跨进程继承的隐患。
    """
    import os
    if endpoint:
        os.environ["RUSTFS_ENDPOINT"] = endpoint
        import annual_semi_extraction.rustfs as _rustfs
        _rustfs.ENDPOINT_URL = endpoint
        _rustfs._server_time_offset = None
    # combo 只用 headings/pattern，不需要 frozen_verdict；关掉可省约 1/3 CPU
    os.environ["H1_FROZEN_EMIT"] = "0"
    from annual_semi_extraction.rustfs import get_client
    _COMBO_STATE["client"] = get_client()
    work_dir = Path(tmp_root) / f"w{os.getpid()}"
    work_dir.mkdir(parents=True, exist_ok=True)
    _COMBO_STATE["tmp_dir"] = work_dir


def _combo_worker(key: str) -> tuple[str, dict | None]:
    """下载 + 抽取，只回传精简结果，不跨进程传递 MD 正文。"""
    client = _COMBO_STATE["client"]
    tmp_path = _COMBO_STATE["tmp_dir"] / key.rsplit("/", 1)[-1]
    try:
        content = client.read_text(key)
        tmp_path.write_text(content, encoding="utf-8")
        rec = extract(tmp_path)
        if rec is None:
            return "no_slot", None
        headings = rec.get("headings", [])
        if not headings:
            return "no_headings", None
        pattern = tuple(
            h.get("raw_name", "") for h in headings if h.get("raw_name", "")
        )
        if not pattern:
            return "empty_pattern", None
        # 复用 extract() 内已完成的判定，判定口径与标准流程严格一致
        if rec.get("library_match"):
            return "library_match", None
        return "ok", {
            "pattern": pattern,
            "slot_key": rec["slot_key"],
            "headings": headings,
            "is_complete_l1": rec.get("is_complete_l1", False),
            "coverage_ratio": rec.get("coverage_ratio", 0.0),
            "extraction_method": rec.get("extraction_method", "unknown"),
        }
    except Exception as e:
        return "exception", f"{key}: {type(e).__name__}: {e}"
    finally:
        tmp_path.unlink(missing_ok=True)


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
    parallel: int = typer.Option(
        16,
        "--parallel", "-j",
        help="并行进程数（默认 16；pro 主机 16 核实测 4/8/12/16 仍线性加速）",
    ),
    endpoint: Optional[str] = typer.Option(
        None,
        "--endpoint", "-e",
        help="RustFS endpoint。在 RustFS 本机用 http://127.0.0.1:9000 直连明文端口，绕过 TLS 握手",
    ),
):
    """从 RustFS 全量抽取 H1 标题，生成去重组合库（多进程并行）。

    流程：
    1. 分页列出 RustFS 上所有 MD 文件
    2. 多进程并行下载 + 抽取 H1（I/O 等待与 CPU 解析同时重叠）
    3. 主进程按输入顺序确定性归约，保证输出幂等
    4. 输出每种组合的出现次数、代表样本、覆盖率统计
    """
    import os
    import shutil
    import time
    from collections import Counter, defaultdict
    from concurrent.futures import ProcessPoolExecutor

    # endpoint 必须在 fork/forkserver 之前写进环境，子进程 import 时才会生效
    if endpoint:
        os.environ["RUSTFS_ENDPOINT"] = endpoint
        import annual_semi_extraction.rustfs as _rustfs
        _rustfs.ENDPOINT_URL = endpoint
        _rustfs._server_time_offset = None

    # fail-fast：worker 依赖 extract() 产出的 library_match。若部署的是旧版
    # extractor.py（历史上发生过），宁可报错也不能静默产出未过滤的结果。
    import annual_semi_extraction.h1.extractor as _ext_mod
    if not getattr(_ext_mod, "HAS_LIBRARY_MATCH", False):
        typer.echo("错误：extractor.py 版本过旧，缺少 library_match 标准流程。"
                   "请同步代码后再运行，否则命中标准库的 pattern 会被误计入统计。",
                   err=True)
        raise typer.Exit(code=2)
    if not getattr(_ext_mod, "HAS_TITLE_ANCHOR", False):
        typer.echo("错误：extractor.py 版本过旧，缺少标题级锚定。"
                   "请同步代码后再运行，否则贪心污染标题会被原样计入组合库。",
                   err=True)
        raise typer.Exit(code=2)
    from annual_semi_extraction.h1.pattern_matcher import get_pattern_matcher
    matcher = get_pattern_matcher()
    if not matcher.is_available or matcher.size == 0:
        typer.echo("错误：标准库不可用或为空，组合库会失去过滤意义。", err=True)
        raise typer.Exit(code=2)
    if matcher.title_count == 0:
        typer.echo("错误：标准库标题词表为空，标题级锚定不会生效。", err=True)
        raise typer.Exit(code=2)
    typer.echo(f"标准库: {matcher.size} 条 pattern, {matcher.title_count} 个标题词条; "
               f"标题锚定 {'开启' if _ext_mod._TITLE_ANCHOR_ENABLED else '关闭'}")

    client = get_client()

    # 1. 列出所有 MD 文件（主进程串行，约 24s 固定开销）
    typer.echo(f"列出 RustFS 对象（前缀 {prefix}, endpoint {client.endpoint}）...")
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

    # 2. 多进程并行处理
    combo_counter: Counter = Counter()
    combo_samples: dict = defaultdict(list)
    combo_headings: dict = {}
    combo_coverage: dict = {}

    n_ok = 0
    n_library_matched = 0
    fail_reasons: Counter = Counter()
    exception_samples: list[str] = []
    tmp_root = Path(tempfile.mkdtemp(prefix="h1_combo_"))
    keys = [obj["key"] for obj in md_objects]

    typer.echo(f"开始并行抽取（{parallel} 进程）...")
    t_start = time.perf_counter()
    try:
        with ProcessPoolExecutor(
            max_workers=parallel,
            initializer=_combo_worker_init,
            initargs=(endpoint, str(tmp_root)),
        ) as executor:
            # executor.map 按输入顺序返回 → 归约确定性，不依赖完成顺序
            for i, (status, result) in enumerate(
                executor.map(_combo_worker, keys, chunksize=16), start=1
            ):
                if status == "ok" and result:
                    n_ok += 1
                    pattern = result["pattern"]
                    combo_counter[pattern] += 1
                    if len(combo_samples[pattern]) < 5:
                        combo_samples[pattern].append(result["slot_key"])
                    if pattern not in combo_headings:
                        combo_headings[pattern] = result["headings"]
                    if pattern not in combo_coverage:
                        combo_coverage[pattern] = {
                            "is_complete_l1": result["is_complete_l1"],
                            "coverage_ratio": result["coverage_ratio"],
                            "extraction_method": result["extraction_method"],
                        }
                elif status == "library_match":
                    n_library_matched += 1
                else:
                    fail_reasons[status] += 1
                    if status == "exception" and len(exception_samples) < 10:
                        exception_samples.append(str(result))

                if i % 10000 == 0:
                    elapsed = time.perf_counter() - t_start
                    typer.echo(f"  进度: {i}/{len(keys)} ({i/elapsed:.1f} f/s), "
                              f"成功 {n_ok}, 标准库命中 {n_library_matched}, "
                              f"唯一组合 {len(combo_counter)}")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    elapsed = time.perf_counter() - t_start
    n_fail = sum(fail_reasons.values())
    typer.echo(f"并行处理耗时 {elapsed:.1f}s ({len(keys)/elapsed:.1f} files/s)")
    typer.echo(f"失败分类: {dict(fail_reasons)}")
    if exception_samples:
        typer.echo("异常样本:", err=True)
        for s in exception_samples:
            typer.echo(f"  {s}", err=True)

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
