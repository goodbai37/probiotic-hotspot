#!/usr/bin/env python3
"""一次性: 给 data.json 现有条目补摘要要点 (abstract 字段)。
用法: python3 backfill_abstract.py [--no-net]  (--no-net 仅展示将写入的内容不落盘)
"""
import json, re, sys
from pathlib import Path
from update_hotspot import pubmed_abstracts, smart_abst

BASE = Path(__file__).parent
DATA_JSON = BASE / "data.json"

def main():
    records = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    pmids = []
    for rec in records:
        for it in rec.get("items", []):
            if it.get("source") == "pubmed" and it.get("url"):
                pmid = it["url"].rstrip("/").split("/")[-1]
                if pmid.isdigit():
                    it["_pmid"] = pmid
                    pmids.append(pmid)
    pmids = list(dict.fromkeys(pmids))
    print(f"需要补摘要的 PMID: {len(pmids)}")

    absts = pubmed_abstracts(pmids)
    filled = 0
    for rec in records:
        for it in rec.get("items", []):
            pmid = it.pop("_pmid", None)
            if pmid and pmid in absts and absts[pmid]:
                it["abstract"] = smart_abst(absts[pmid], 320)
                filled += 1
    print(f"已补摘要: {filled} 条")

    if "--no-net" in sys.argv:
        print("(--no-net 模式, 不写盘)")
        return
    DATA_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {DATA_JSON}")

if __name__ == "__main__":
    main()
