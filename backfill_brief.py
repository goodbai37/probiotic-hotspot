#!/usr/bin/env python3
"""一次性: 给 data.json 现有条目补中文内容概括 (brief 字段)。

文献(pubmed)用摘要, 法规(foodmate)抓详情页正文, nhc 用标题。
复用 update_hotspot 的 llm_brief。
用法: python3 backfill_brief.py [--no-net]
"""
import json, sys
from pathlib import Path
from update_hotspot import llm_brief, _foodmate_content

BASE = Path(__file__).parent
DATA_JSON = BASE / "data.json"

def main():
    records = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    # 收集所有缺 brief 的条目
    need = []
    for rec in records:
        for it in rec.get("items", []):
            if it.get("brief"):
                continue
            # foodmate 抓正文(缓存到条目, 避免重复抓)
            if it.get("source") == "foodmate" and not it.get("content"):
                it["content"] = _foodmate_content(it.get("url", ""))
            need.append(it)
    print(f"需补概括: {len(need)} 条")
    if not need:
        print("全部已有 brief, 无需处理")
        return
    llm_brief(need)  # 就地写 it["brief"]
    filled = sum(1 for it in need if it.get("brief"))
    print(f"已补概括: {filled} 条")

    if "--no-net" in sys.argv:
        print("(--no-net 模式, 不写盘)")
        return
    DATA_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {DATA_JSON}")

if __name__ == "__main__":
    main()
