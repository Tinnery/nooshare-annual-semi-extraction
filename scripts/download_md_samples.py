"""从 RustFS 下载 MD 样本文件用于章节 pattern 分析。"""
import os
import sys
import boto3
from botocore.config import Config

# RustFS 配置
ENDPOINT_URL = "https://s3.rustfs.pro.neuralj.com"
ACCESS_KEY = "charlie"
SECRET_KEY = "sheeta-rustfs"
BUCKET = "annual-semi"

# 2021-2024 年报(P4)和半年报(P2)样本
SAMPLE_KEYS = [
    # 000001 平安银行 - 不同年份
    "published/000001/000001_2021_4.md",
    "published/000001/000001_2022_4.md",
    "published/000001/000001_2023_4.md",
    "published/000001/000001_2024_4.md",
    "published/000001/000001_2023_2.md",
    "published/000001/000001_2024_2.md",
    # 其他股票样本
    "published/600519/600519_2023_4.md",
    "published/300750/300750_2023_4.md",
]

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "md_samples")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    config = Config(signature_version='s3v4', s3={'addressing_style': 'path'})
    client = boto3.client(
        's3',
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        verify=False,
        config=config,
    )
    
    for key in SAMPLE_KEYS:
        fname = os.path.basename(key)
        out_path = os.path.join(OUTPUT_DIR, fname)
        print(f"Downloading {key} -> {fname}")
        try:
            client.download_file(BUCKET, key, out_path)
            print(f"  OK ({os.path.getsize(out_path)} bytes)")
        except Exception as e:
            print(f"  FAILED: {e}")
    
    print("Done")


if __name__ == "__main__":
    main()
