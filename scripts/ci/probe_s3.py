#!/usr/bin/env python3
"""RustFS 真连探针（经 stunnel 本地端口）。

canary 对象 上传→下载→SHA256 一致才算 PASS。
异常只映射为错误码，绝不打印异常对象（可能含 endpoint/签名/密钥线索）。
"""
import os
import sys
import hashlib

try:
    import boto3
except ImportError:
    print("S3_PROBE=FAIL code=S3_NO_BOTO3")
    sys.exit(1)

def audit(line):
    print(line)
    try:
        with open(os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "ci_audit.log"), "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def classify_exception(exc):
    """把异常映射为固定错误码，绝不回显异常文本（可能含 endpoint/签名/密钥线索）。"""
    from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError, ConnectTimeoutError, ReadTimeoutError
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
        return "S3_CLIENT_" + str(code)[:24]
    # 兜底回显异常类名（公开类型信息，不含数据），供进一步定位
    return "S3_EXC_TYPE_" + tname[:28]

access = os.environ.get("RUSTFS_ACCESS_KEY")
secret = os.environ.get("RUSTFS_SECRET_KEY")
bucket = os.environ.get("RUSTFS_BUCKET", "nooshare-ci-probe")
endpoint = os.environ.get("S3_LOCAL_ENDPOINT", "http://127.0.0.1:15500")

if not access or not secret:
    audit("S3_PROBE=FAIL code=S3_NO_CRED")
    sys.exit(1)

# 只输出长度（非敏感），便于确认凭据格式
audit(f"S3_CRED_SHAPE access_len={len(access)} secret_len={len(secret)}")

try:
    from botocore.config import Config
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
        # 1) path-style：经隧道时 Host 固定为 127.0.0.1:port，避免 bucket 拼入 Host
        # 2) 关闭新版 boto3 的 flexible checksum：旧版 RustFS 不识别 x-amz-checksum-crc32，
        #    会因此报 SignatureDoesNotMatch（pro 上旧 boto3 直连正常即为佐证）
        config=Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )

    # 1) 列 bucket —— 验证身份可读
    buckets = s3.list_buckets().get("Buckets", [])
    if not any(b["Name"] == bucket for b in buckets):
        audit("S3_PROBE=FAIL code=S3_BUCKET_MISSING")
        sys.exit(1)

    # 2) 越权检查：尝试列专用 bucket 之外的桶。
    #    最小权限是纵深防御目标，不是连通性判据：权限过宽记为 warning 并继续，
    #    不掩盖 canary 读写验证（root key 是已知偏差，仍证明访问已调通）。
    denied_ok = False
    over_broad = False
    for b in buckets:
        if b["Name"] != bucket:
            try:
                s3.list_objects_v2(Bucket=b["Name"], MaxKeys=1)
                over_broad = True  # 未报错 = 权限过宽
            except Exception:
                denied_ok = True
            break
    if over_broad:
        audit("S3_WARN=OVERPRIVILEGED (credential can list other buckets; known deviation)")
        overpriv = "overbroad"
    elif denied_ok:
        overpriv = "denied"
    else:
        overpriv = "skip"

    # 3) canary 对象 上传→下载→SHA256
    payload = b"ci-canary-" + os.urandom(32)
    key = "canary/probe.bin"
    s3.put_object(Bucket=bucket, Key=key, Body=payload)
    got = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    if hashlib.sha256(payload).hexdigest() != hashlib.sha256(got).hexdigest():
        audit("S3_PROBE=FAIL code=S3_SHA_MISMATCH")
        sys.exit(1)
    s3.delete_object(Bucket=bucket, Key=key)

    audit(f"S3_PROBE=PASS overpriv={overpriv}")
    sys.exit(0)

except SystemExit:
    raise
except Exception as e:
    audit(f"S3_PROBE=FAIL code={classify_exception(e)}")
    sys.exit(1)
