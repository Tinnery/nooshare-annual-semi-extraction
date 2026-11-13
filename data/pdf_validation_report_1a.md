# 阶段1a 扩量回归验证报告

- 抽样 491 份 | 解析成功 484 | 下载成功 484 | 提取成功 482
- 用时 276.9s

## 策略分布
```json
{"numbering": 427, "bookmark": 21, "font_fallback": 34}
```

## 门禁
- numbering 命中率: **88.6%** (门禁 >=80%) → PASS
- 法定纯度(numbering内均值): **96.6%** (门禁 >=88%) → PASS
- 编号连续率: 93.4% | 平均标题数: 10.7
- 年代分布: {"new_annual": 422, "old_semi": 3, "old_annual": 2}

## 总判定: **PASS — 进入阶段1b**

## MD 对齐率 (numbering样本内, 以PDF为参照)

| 层 | 样本数 | MD标题总数 | 对齐 | 对齐率 |
|---|---|---|---|---|
| general_complete | 148 | 1709 | 1550 | 90.7% |
| y2021_complete | 50 | 575 | 521 | 90.6% |
| ch_zh_incomplete | 74 | 629 | 551 | 87.6% |
| md_h1_incomplete | 77 | 181 | 7 | 3.9% |
| md_h1_complete | 4 | 53 | 33 | 62.3% |
| bank_format | 49 | 499 | 434 | 87.0% |
| retry_stage0 | 2 | 15 | 13 | 86.7% |
