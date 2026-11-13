"""验证形态修正没有破坏 M2 可回放性。

不变量：
1. 每个 segment 的 [start,end) 必须落在原 H1 文本范围内，且切片非空；
2. 每个 clean_name 必须来自外部有限集（法规节名 + 上游 canonical 变体），
   禁止出现修正过程发明的新字符串；
3. 原 verbatim 一字未改（byte offset 与 sha 与原 corpus 一致）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from heading_morphology import LEGAL_NAMES  # noqa: E402

ORIG = Path("data/heading_corpus.jsonl")
CLEAN = Path("data/heading_corpus_clean.jsonl")
LEGAL = set(LEGAL_NAMES)


def main() -> None:
    orig = [json.loads(l) for l in ORIG.open(encoding="utf-8")]
    clean = [json.loads(l) for l in CLEAN.open(encoding="utf-8")]
    assert len(orig) == len(clean), "行数不一致"
    by_key = {r["slot_key"]: r for r in orig}

    n_seg = n_h1 = 0
    bad_span = bad_name = bad_verbatim = 0
    examples = []
    for c in clean:
        o = by_key.get(c["slot_key"])
        if o is None or o["source_sha256"] != c["source_sha256"]:
            bad_verbatim += 1
            continue
        for h, ch in zip(o["h1"], c["h1_classified"]):
            n_h1 += 1
            if (h["start"], h["end"], h["line"]) != (ch["start"], ch["end"], ch["line"]):
                bad_verbatim += 1
            text = h["text"]
            for sg in ch["segments"]:
                n_seg += 1
                s, e = sg["start"], sg["end"]
                if not (0 <= s < e <= len(text)):
                    bad_span += 1
                    if len(examples) < 5:
                        examples.append(("span", c["slot_key"], s, e, len(text)))
                for nm in ch["clean_names"]:
                    if nm not in LEGAL:
                        bad_name += 1
                        if len(examples) < 5:
                            examples.append(("name", c["slot_key"], nm))
                        break

    print(f"报告数        {len(clean)}")
    print(f"H1 数         {n_h1}")
    print(f"segment 数    {n_seg}")
    print(f"span 越界     {bad_span}")
    print(f"自造名称      {bad_name}")
    print(f"verbatim/偏移不一致 {bad_verbatim}")
    print(f"外部有限集大小 {len(LEGAL)}")
    if examples:
        print("样例:", examples)
    ok = bad_span == 0 and bad_name == 0 and bad_verbatim == 0
    print("\n结论:", "PASS — 修正为纯派生，M2 未被破坏" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
