#!/usr/bin/env python3
"""H1 语料批量下载：从 RustFS annual-semi 桶枚举并下载 published/ 下的 MD 文件。

职责边界（窄）：
- 只读操作：list_objects_v2 + get_object
- 不执行 H1 抽取（那是 h1-extract CLI 的职责）
- 不连接 PG / 不写入数据库
- 不执行上游 MD 完整性检查（只消费已发布的语料）

输出：
1. 本地目录结构：{output_dir}/published/<code>/<code>_<year>_<period>.md
2. input-manifest.jsonl：每行一份文件的元数据（本地路径、S3 key、SHA256、大小、slot_key）
3. batch-summary.json：批次统计（文件数、总字节数、成功/失败数、失败清单）

安全：
- 异常只映射为错误码，绝不打印异常对象（可能含 endpoint/签名/密钥线索）
- 凭据从环境变量读取（CI secrets 注入），不落盘
"""
import os
import sys
import json
import hashlib
import re
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    print("CORPUS_DOWNLOAD=FAIL code=S3_NO_BOTO3")
    sys.exit(1)


def audit(line: str) -> None:
    """输出审计行到 stdout 和审计日志文件。"""
    print(line)
    try:
        work_dir = os.environ.get("RUNNER_TEMP", "/tmp")
        with open(os.path.join(work_dir, "ci_audit.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def classify_exception(exc: Exception) -> str:
    """把异常映射为固定错误码，绝不回显异常文本（可能含 endpoint/签名/密钥线索）。"""
    from botocore.exceptions import EndpointConnectionError, NoCredentialsError, ConnectTimeoutError, ReadTimeoutError
    tname = type(exc).__name__
    if isinstance(exc, EndpointConnectionError) or "EndpointConnection" in tname:
        return "S3_ENDPOINT_UNREACHABLE"
    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)) or "Timeout" in tname:
        return "S3_TIMEOUT"
    if "ConnectionClosed" in tname or "ProtocolError" in tname or "RemoteDisconnected" in tname:
        return "S3_CONN_DROP"
    if isinstance(exc, NoCredentialsError):
        return "S3_NO_CRED"
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "InvalidAccessKeyId":
            return "S3_BAD_KEY_ID"
        if code == "SignatureDoesNotMatch":
            return "S3_BAD_SIGNATURE"
        if code in ("AccessDenied", "InvalidSecurity"):
            return "S3_ACCESS_DENIED"
        if code == "NoSuchBucket":
            return "S3_BUCKET_MISSING"
        if code == "NoSuchKey":
            return "S3_KEY_MISSING"
        return "S3_CLIENT_" + str(code)[:24]
    return "S3_EXC_TYPE_" + tname[:28]


def extract_slot_key(s3_key: str) -> Optional[str]:
    """只接受 published/<6位代码>/<代码>_<年份>_<2或4>.md。"""
    parts = s3_key.split("/")
    if len(parts) != 3 or parts[0] != "published":
        return None
    code = parts[1]
    match = re.fullmatch(r"(\d{6})_(\d{4})_([24])\.md", parts[2])
    if not re.fullmatch(r"\d{6}", code) or match is None:
        return None
    if match.group(1) != code:
        return None
    return parts[2][:-3]


def main():
    # 环境变量
    access = os.environ.get("RUSTFS_ACCESS_KEY")
    secret = os.environ.get("RUSTFS_SECRET_KEY")
    bucket = os.environ.get("RUSTFS_BUCKET", "annual-semi")
    endpoint = os.environ.get("S3_LOCAL_ENDPOINT", "http://127.0.0.1:15500")
    output_dir = os.environ.get("CORPUS_OUTPUT_DIR", "corpus-data")
    prefix = os.environ.get("CORPUS_PREFIX", "published/")
    try:
        limit = int(os.environ.get("CORPUS_LIMIT", "0"))  # 0 = 不限制
    except ValueError:
        audit("CORPUS_DOWNLOAD=FAIL code=INVALID_LIMIT")
        sys.exit(1)
    start_after = os.environ.get("CORPUS_START_AFTER", "").strip()

    if not access or not secret:
        audit("CORPUS_DOWNLOAD=FAIL code=S3_NO_CRED")
        sys.exit(1)

    audit(f"CORPUS_CONFIG bucket={bucket} prefix={prefix} output_dir={output_dir}")

    # 创建输出目录
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 构建 S3 客户端（复用 probe_s3.py 的配置）
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name="us-east-1",
            config=Config(
                s3={"addressing_style": "path"},
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=90,
                retries={"max_attempts": 3, "mode": "standard"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
    except Exception as e:
        audit(f"CORPUS_DOWNLOAD=FAIL code={classify_exception(e)}")
        sys.exit(1)

    # 1) 枚举 published/ 下符合年报/半年报槽位格式的 MD 文件
    audit("CORPUS_ENUMERATE start")
    keys_to_download: list[str] = []
    object_metadata: dict[str, dict] = {}
    n_ignored_malformed = 0
    try:
        paginator = s3.get_paginator("list_objects_v2")
        pagination_args = {"Bucket": bucket, "Prefix": prefix}
        if start_after:
            pagination_args["StartAfter"] = start_after
        for page in paginator.paginate(**pagination_args):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".md"):
                    continue
                if extract_slot_key(key) is None:
                    n_ignored_malformed += 1
                    continue
                keys_to_download.append(key)
                object_metadata[key] = {
                    "size": int(obj.get("Size", 0)),
                    "etag": obj.get("ETag"),
                    "last_modified": obj.get("LastModified"),
                }
                if limit > 0 and len(keys_to_download) >= limit:
                    break
            if limit > 0 and len(keys_to_download) >= limit:
                break
    except Exception as e:
        audit(f"CORPUS_ENUMERATE=FAIL code={classify_exception(e)}")
        sys.exit(1)

    n_enumerated = len(keys_to_download)
    audit(f"CORPUS_ENUMERATE done n={n_enumerated} ignored_malformed={n_ignored_malformed}")

    if n_enumerated == 0:
        if start_after and os.environ.get("CORPUS_INVENTORY_ONLY", "0") != "1":
            summary = {
                "n_enumerated": 0,
                "n_downloaded": 0,
                "n_failed": 0,
                "n_ignored_malformed": n_ignored_malformed,
                "start_after": start_after,
                "end_of_corpus": True,
                "manifest_path": None,
                "output_dir": str(out_path),
            }
            (out_path / "batch-summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            audit("CORPUS_ENUMERATE=END_OF_CORPUS")
            sys.exit(0)
        audit("CORPUS_DOWNLOAD=FAIL code=NO_FILES_FOUND")
        sys.exit(1)

    # Inventory 模式仅读取 ListObjects 元数据；不下载 MD、不运行 H1、不写 PG。
    if os.environ.get("CORPUS_INVENTORY_ONLY", "0") == "1":
        manifest_path = out_path / "input-manifest.jsonl"
        annual_count = 0
        semi_count = 0
        stocks: set[str] = set()
        years: list[int] = []
        total_bytes = 0
        with manifest_path.open("w", encoding="utf-8") as f_manifest:
            for key in keys_to_download:
                slot_key = extract_slot_key(key)
                code, year_s, period_s = slot_key.split("_")
                meta = object_metadata[key]
                total_bytes += meta["size"]
                stocks.add(code)
                years.append(int(year_s))
                if period_s == "4":
                    annual_count += 1
                else:
                    semi_count += 1
                modified = meta["last_modified"]
                f_manifest.write(json.dumps({
                    "s3_key": key,
                    "slot_key": slot_key,
                    "size": meta["size"],
                    "etag": meta["etag"],
                    "last_modified": modified.isoformat() if modified else None,
                    "status": "INVENTORY_ONLY",
                }, ensure_ascii=False) + "\n")

        summary = {
            "mode": "inventory_only",
            "n_enumerated": n_enumerated,
            "n_downloaded": 0,
            "n_failed": 0,
            "n_ignored_malformed": n_ignored_malformed,
            "n_inventory_rows": n_enumerated,
            "first_key": keys_to_download[0],
            "last_key": keys_to_download[-1],
            "estimated_total_bytes": total_bytes,
            "stock_count": len(stocks),
            "annual_count": annual_count,
            "semi_count": semi_count,
            "report_year_min": min(years),
            "report_year_max": max(years),
            "manifest_path": str(manifest_path),
        }
        (out_path / "batch-summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_path / "corpus-inventory.jsonl").write_text(
            manifest_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        audit(
            f"CORPUS_INVENTORY=PASS objects={n_enumerated} bytes={total_bytes} "
            f"stocks={len(stocks)} annual={annual_count} semi={semi_count}"
        )
        sys.exit(0)

    # 2) 批量下载 + 计算 SHA256（并发模式）
    manifest_path = out_path / "input-manifest.jsonl"
    n_downloaded = 0
    n_failed = 0
    total_bytes = 0
    failed_keys: list[str] = []

    # 并发配置：默认 4 workers，可通过环境变量调整
    max_workers = int(os.environ.get("CORPUS_DOWNLOAD_WORKERS", "4"))
    
    def download_one(key: str) -> dict:
        """下载单个文件并返回结果（不写入 manifest）。"""
        local_file = out_path / key
        local_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            response = s3.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()
            expected_length = int(response.get("ContentLength", len(body)))
            if expected_length != len(body):
                raise ValueError("S3_CONTENT_LENGTH_MISMATCH")
            local_file.write_bytes(body)
            
            sha = hashlib.sha256(body).hexdigest()
            size = len(body)
            slot_key = extract_slot_key(key)
            
            return {
                "status": "ok",
                "path": str(local_file),
                "s3_key": key,
                "sha256": sha,
                "size": size,
                "slot_key": slot_key,
                "etag": response.get("ETag"),
                "last_modified": response.get("LastModified").isoformat()
                if response.get("LastModified") else None,
            }
        except Exception as e:
            return {
                "status": "fail",
                "s3_key": key,
                "error_code": classify_exception(e),
            }

    audit(f"CORPUS_DOWNLOAD start workers={max_workers}")
    
    # 并发下载，按原始顺序处理结果（断点续传依赖 last_key 顺序）
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results_by_key: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key = {executor.submit(download_one, key): key for key in keys_to_download}
        
        # 按完成顺序收集结果
        for i, future in enumerate(as_completed(future_to_key), start=1):
            result = future.result()
            results_by_key[result["s3_key"]] = result
            
            if i % 1000 == 0:
                audit(f"CORPUS_DOWNLOAD progress {i}/{n_enumerated}")
    
    # 按原始顺序写入 manifest（保持 slot_key 顺序，断点续传依赖）
    audit("CORPUS_MANIFEST_WRITE start")
    with manifest_path.open("w", encoding="utf-8") as f_manifest:
        for key in keys_to_download:
            result = results_by_key[key]
            if result["status"] == "ok":
                f_manifest.write(json.dumps({
                    "path": result["path"],
                    "s3_key": result["s3_key"],
                    "sha256": result["sha256"],
                    "size": result["size"],
                    "slot_key": result["slot_key"],
                    "etag": result["etag"],
                    "last_modified": result["last_modified"],
                }, ensure_ascii=False) + "\n")
                n_downloaded += 1
                total_bytes += result["size"]
            else:
                n_failed += 1
                failed_keys.append(result["s3_key"])
                audit(f"CORPUS_DOWNLOAD_FAIL key={result['s3_key']} code={result['error_code']}")

    audit(f"CORPUS_DOWNLOAD done ok={n_downloaded} fail={n_failed} bytes={total_bytes}")

    # 3) 写入批次摘要
    summary = {
        "n_enumerated": n_enumerated,
        "n_downloaded": n_downloaded,
        "n_failed": n_failed,
        "n_ignored_malformed": n_ignored_malformed,
        "start_after": start_after or None,
        "first_key": keys_to_download[0],
        "last_key": keys_to_download[-1],
        "next_start_after": keys_to_download[-1],
        "has_more": bool(limit > 0 and n_enumerated >= limit),
        "total_bytes": total_bytes,
        "failed_keys": failed_keys[:100],  # 只保留前 100 个失败 key，避免摘要过大
        "manifest_path": str(manifest_path),
        "output_dir": str(out_path),
    }
    summary_path = out_path / "batch-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    audit(f"CORPUS_SUMMARY written to {summary_path}")

    # 4) 最终判定
    if n_downloaded == 0:
        audit("CORPUS_DOWNLOAD=FAIL code=ALL_FAILED")
        sys.exit(1)
    elif n_failed > 0:
        audit(f"CORPUS_DOWNLOAD=PARTIAL ok={n_downloaded} fail={n_failed}")
        sys.exit(1)  # 部分下载不得伪装为完整成功
    else:
        audit("CORPUS_DOWNLOAD=PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
