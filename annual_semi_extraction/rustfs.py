"""RustFS 客户端：读取远程 MD 文件。

RustFS 是 S3 兼容对象存储，部署在局域网（192.168.31.233）。

已知问题：RustFS 服务器时钟有约 8 小时偏差（把 GMT+8 本地时间当 UTC 返回），
导致 boto3 的 S3v4 签名（用真实 UTC）被服务器以 RequestTimeTooSkewed 拒绝。
本模块绕过 boto3，用 urllib 直接计算 S3v4 签名，以服务器报告的时间为准。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import ssl
import datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# RustFS 配置（与 scripts/fetch_all_md.py 保持一致）
# 在 RustFS 本机运行时可设 RUSTFS_ENDPOINT=http://127.0.0.1:9000 直连明文端口，
# 绕过 TLS 握手；默认仍走域名 HTTPS。
ENDPOINT_URL = os.environ.get("RUSTFS_ENDPOINT", "https://s3.rustfs.pro.neuralj.com")
ACCESS_KEY = "charlie"
SECRET_KEY = "sheeta-rustfs"
BUCKET = "annual-semi"
REGION = "us-east-1"
SERVICE = "s3"

# 缓存的时间偏移量（本机 UTC → 服务器"UTC"）
_server_time_offset: Optional[datetime.timedelta] = None

# 不验证 SSL 的 context（与 boto3 verify=False 一致）
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def _new_connection(timeout: int = 30):
    """按 ENDPOINT_URL 的 scheme 创建连接：http 走明文端口，https 走 TLS。"""
    parsed = urlparse(ENDPOINT_URL)
    if parsed.scheme == "http":
        return HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
    return HTTPSConnection(parsed.hostname, parsed.port or 443, context=_SSL_CTX, timeout=timeout)


def _get_server_time_offset() -> datetime.timedelta:
    """获取本机 UTC 与 RustFS 服务器报告时间的偏差（只计算一次）。

    服务器 Date 头把 GMT+8 本地时间标为 GMT，我们把它当作服务器的"UTC"来用，
    这样签名时间就和服务器预期一致，不会触发 RequestTimeTooSkewed。
    """
    global _server_time_offset
    if _server_time_offset is not None:
        return _server_time_offset
    try:
        conn = _new_connection(timeout=5)
        conn.request("HEAD", "/")
        resp = conn.getresponse()
        date_str = resp.getheader("Date")
        conn.close()
        if date_str:
            server_time = parsedate_to_datetime(date_str)
            server_utc = server_time.replace(tzinfo=datetime.timezone.utc)
            local_utc = datetime.datetime.now(datetime.timezone.utc)
            _server_time_offset = server_utc - local_utc
        else:
            _server_time_offset = datetime.timedelta(0)
    except Exception:
        _server_time_offset = datetime.timedelta(0)
    return _server_time_offset


def _hmac_sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signing_key(date_stamp: str) -> bytes:
    k_date = _hmac_sign(("AWS4" + SECRET_KEY).encode("utf-8"), date_stamp)
    k_region = _hmac_sign(k_date, REGION)
    k_service = _hmac_sign(k_region, SERVICE)
    return _hmac_sign(k_service, "aws4_request")


def _build_signed_headers(method: str, path: str, query_string: str = "") -> dict:
    """用服务器时间计算 S3v4 签名，返回完整请求头。"""
    offset = _get_server_time_offset()
    signing_time = datetime.datetime.now(datetime.timezone.utc) + offset
    date_stamp = signing_time.strftime("%Y%m%d")
    amz_date = signing_time.strftime("%Y%m%dT%H%M%SZ")

    parsed = urlparse(ENDPOINT_URL)
    host = parsed.netloc
    content_sha256 = "UNSIGNED-PAYLOAD"  # GET/HEAD 请求无需 payload hash

    headers_to_sign = {
        "host": host,
        "x-amz-content-sha256": content_sha256,
        "x-amz-date": amz_date,
    }
    signed_keys = sorted(headers_to_sign)
    signed_headers_str = ";".join(signed_keys)
    canonical_headers = "".join(f"{k}:{headers_to_sign[k]}\n" for k in signed_keys)

    canonical_request = "\n".join([
        method,
        path,
        query_string,      # query string（分页需要）
        canonical_headers,
        signed_headers_str,
        content_sha256,
    ])

    credential_scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signing_key(date_stamp)
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    auth = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, "
        f"Signature={signature}"
    )

    return {
        "Host": host,
        "x-amz-content-sha256": content_sha256,
        "x-amz-date": amz_date,
        "Authorization": auth,
    }


def _object_path(key: str) -> str:
    """构造 S3 path-style 路径：/{bucket}/{key}。"""
    return f"/{BUCKET}/{key.lstrip('/')}"


def _do_request(method: str, path: str, query_string: str = "") -> tuple[int, bytes]:
    """执行签名后的 HTTP(S) 请求，返回 (status_code, body)。"""
    headers = _build_signed_headers(method, path, query_string)
    full_path = f"{path}?{query_string}" if query_string else path
    conn = _new_connection(timeout=30)
    try:
        conn.request(method, full_path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        return status, body
    finally:
        conn.close()


class RustFSClient:
    """RustFS 读取客户端。

    用法:
        client = RustFSClient()
        content = client.read_text("published/000001/000001_2024_4.md")
    """

    @property
    def endpoint(self) -> str:
        """当前使用的 endpoint（便于日志确认是否走了本机明文端口）。"""
        return ENDPOINT_URL

    def read_text(self, key: str) -> str:
        """读取指定 key 的文本内容。

        Args:
            key: 对象路径，如 "published/000001/000001_2024_4.md"

        Returns:
            UTF-8 解码的文本内容

        Raises:
            FileNotFoundError: 对象不存在
            RuntimeError: 其他 HTTP 错误
        """
        path = _object_path(key)
        status, body = _do_request("GET", path)
        if status == 404:
            raise FileNotFoundError(f"RustFS 对象不存在: {key}")
        if status != 200:
            raise RuntimeError(
                f"RustFS 请求失败 [{status}]: {body[:200].decode('utf-8', errors='replace')}"
            )
        return body.decode("utf-8")

    def read_bytes(self, key: str) -> bytes:
        """读取指定 key 的原始字节。"""
        path = _object_path(key)
        status, body = _do_request("GET", path)
        if status == 404:
            raise FileNotFoundError(f"RustFS 对象不存在: {key}")
        if status != 200:
            raise RuntimeError(f"RustFS 请求失败 [{status}]")
        return body

    def exists(self, key: str) -> bool:
        """检查对象是否存在。"""
        path = _object_path(key)
        status, _ = _do_request("HEAD", path)
        return status == 200

    def download_file(self, key: str, local_path: Path) -> None:
        """下载对象到本地文件。"""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.read_bytes(key)
        local_path.write_bytes(content)

    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> list[dict]:
        """列出指定前缀下的所有对象（自动分页）。

        Args:
            prefix: 对象前缀，如 "published/"
            max_keys: 每页最大返回数量（S3 限制最大 1000）

        Returns:
            对象列表，每项包含 {"key": str, "size": int, "last_modified": str}
        """
        import xml.etree.ElementTree as ET
        from urllib.parse import quote

        objects = []
        continuation_token = None

        while True:
            path = _object_path("")
            
            # 构建 query string（必须按字母顺序排序，值需要 URL 编码）
            query_params = {
                "list-type": "2",
                "prefix": prefix,
                "max-keys": str(max_keys),
            }
            if continuation_token:
                query_params["continuation-token"] = continuation_token
            
            # 按 key 排序，并对 key 和 value 进行 URL 编码
            query_string = "&".join(
                f"{quote(k, safe='')}={quote(v, safe='')}"
                for k, v in sorted(query_params.items())
            )

            status, body = _do_request("GET", path, query_string)
            if status != 200:
                raise RuntimeError(
                    f"RustFS 列出对象失败 [{status}]: {body[:200].decode('utf-8', errors='replace')}"
                )

            # 解析 XML 响应
            root = ET.fromstring(body)
            ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

            for content in root.findall("s3:Contents", ns):
                key_elem = content.find("s3:Key", ns)
                size_elem = content.find("s3:Size", ns)
                last_modified_elem = content.find("s3:LastModified", ns)
                if key_elem is not None:
                    objects.append({
                        "key": key_elem.text,
                        "size": int(size_elem.text) if size_elem is not None else 0,
                        "last_modified": last_modified_elem.text if last_modified_elem is not None else "",
                    })

            # 检查是否有更多页
            is_truncated = root.find("s3:IsTruncated", ns)
            if is_truncated is not None and is_truncated.text == "true":
                next_token = root.find("s3:NextContinuationToken", ns)
                if next_token is not None:
                    continuation_token = next_token.text
                else:
                    break
            else:
                break

        return objects


# 全局单例（延迟初始化）
_client: Optional[RustFSClient] = None


def get_client() -> RustFSClient:
    """获取全局 RustFS 客户端单例。"""
    global _client
    if _client is None:
        _client = RustFSClient()
    return _client


def read_md(key: str) -> str:
    """快捷函数：读取 MD 文件内容。

    Args:
        key: RustFS 对象路径，如 "published/000001/000001_2024_4.md"

    Returns:
        文本内容
    """
    return get_client().read_text(key)
