#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分模块: 为热点条目计算可解释的热度评分 (0-100)
================================================
评分维度（按类别加权，权重见 SCORE_WEIGHTS，可调）:

  相关文献 / 工艺进展:
    freshness   新鲜度     = exp(-天数/30)，发表越近分越高
    journal     期刊质量   = OpenAlex 2yr_mean_citedness（期刊近2年平均被引，
                            即影响因子的开放替代）分段映射
    cited       被引热度   = OpenAlex cited_by_count（该文全历史被引）分段映射
    evidence    证据等级   = 荟萃/RCT > 人体试验 > 动物/体外
    focus       方向匹配   = 命中关注方向(肠道/骨骼/视力/女性/护肝/儿童)
    specificity 具体性     = 标题含具体菌株名/工艺词

  法规动态 / 菌株专利:
    freshness   新鲜度
    authority   权威性     = 卫健委 > 行业媒体 > 一般媒体
    relevance   相关度     = 标题益生菌关键词命中数
    specificity 具体性     = 含拉丁学名/菌株/组合物等

OpenAlex 查询结果按 PMID 缓存 7 天，避免重复请求。
"""

import json
import logging
import math
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

log = logging.getLogger("scoring")

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "scoring_cache.json"
CACHE_TTL_DAYS = 7

# 各标签维度的权重（总和=1）。调整此处即可改变"热度"的评判侧重。
SCORE_WEIGHTS = {
    "相关文献": {"freshness": 0.25, "journal": 0.20, "cited": 0.10,
                 "evidence": 0.15, "focus": 0.10, "specificity": 0.20},
    "工艺进展": {"freshness": 0.30, "journal": 0.20, "specificity": 0.25,
                 "evidence": 0.10, "focus": 0.15},
    "法规动态": {"freshness": 0.50, "authority": 0.30, "relevance": 0.20},
    "菌株专利": {"freshness": 0.35, "specificity": 0.35, "authority": 0.30},
}

# 关注方向 -> 标题匹配正则（中文/英文）
FOCUS_PATTERNS = {
    "肠道": r"肠道|屏障|便秘|腹泻|肠易激|gut|bowel|constipat|diarrh|barrier|microbiota",
    "骨骼": r"骨|osteop|bone|fracture",
    "视力": r"视|眼|myopia|vision|ocular|eye",
    "女性": r"阴道|女性|妇科|vaginal|vulvovag|women|female|menopaus",
    "护肝": r"肝|hepatic|liver|nafld|fatty",
    "儿童": r"儿童|婴儿|幼儿|infant|pediatric|child|toddler|neonat",
}

# 期刊 2yr_mean_citedness 分段 -> 得分 (下限, 得分)
JOURNAL_BANDS = [(10.0, 1.0), (5.0, 0.8), (2.0, 0.6), (0.5, 0.4)]
# 文章被引数分段 -> 得分
CITED_BANDS = [(50, 1.0), (20, 0.8), (10, 0.6), (3, 0.4), (1, 0.25)]

# 法规/新闻相关度关键词
RELEVANCE_KW = ("益生菌", "菌株", "微生态", "后生元", "新食品原料",
                "乳杆菌", "双歧杆菌", "保健食品", "活菌")
# 具体性关键词
SPECIFIC_KW = ("菌株", "组合物", "配方", "包埋", "冻干", "稳定性",
               "工艺", "微囊", "喷雾干燥")
# 拉丁学名正则: Lactiplantibacillus plantarum / Bifidobacterium animalis subsp. lactis
LATIN_RE = re.compile(r"[A-Z][a-z]{2,}\s+[a-z]{3,}(?:\s+subsp\.\s+[A-Z][a-z]+)?")
# 菌株编号正则: CCFM1445 / BB-12 / Nissle 1917 / Jlus66 / MMX（不用 \b，中文环境边界失效）
STRAIN_CODE_RE = re.compile(
    r"(?:CCFM\d+|BB-?12|LGG|Nissle\s*1917|"          # 已知菌株编号
    r"[A-Z][a-z]{2,}\d{2,}|"                          # 学名+编号 如 Jlus66
    r"[A-Z]{2,}\d{2,}|\b[A-Z]{2,5}\b)"              # 大写编号 / 大写菌株缩写 如 MMX
)


# ----------------------------------------------------------------------------
# 分项评分函数
# ----------------------------------------------------------------------------
def _band_score(value, bands, fallback: float) -> float:
    """按分段表映射: value >= 下限 取对应得分，未命中用 fallback。"""
    if value is None:
        return fallback
    for lo, sc in bands:
        if value >= lo:
            return sc
    return fallback


def freshness(it: dict) -> float:
    """新鲜度: exp(-天数/30)。日期缺失按 0.5 中值。"""
    d = it.get("date", "")
    try:
        days = (date.today() - date.fromisoformat(d)).days
    except (ValueError, TypeError):
        return 0.5
    if days < 0:
        return 1.0
    return round(math.exp(-days / 30), 3)


def evidence_score(it: dict) -> float:
    """证据等级: 荟萃/系统综述 > RCT > 临床试验 > 队列 > 默认。"""
    t = (it.get("title", "") or "").lower()
    pt = " ".join(it.get("pubtype", []) or []).lower()
    if "meta-analysis" in t or "meta-analysis" in pt or "systematic review" in pt:
        return 1.0
    if "randomized" in pt or "randomized" in t or "double-blind" in t:
        return 0.95
    if "clinical trial" in pt or "trial" in t:
        return 0.85
    if "cohort" in t or "case-control" in t:
        return 0.70
    if re.search(r"in vitro|animal|mouse|rat|cell line", t):
        return 0.35
    return 0.50


def focus_score(it: dict) -> float:
    """关注方向匹配: 命中任一方向=1.0，否则 0.3。"""
    t = it.get("title", "") or ""
    for pat in FOCUS_PATTERNS.values():
        if re.search(pat, t, re.I):
            return 1.0
    return 0.3


def specificity_score(it: dict) -> float:
    """具体性: 含拉丁学名/菌株编号=1.0，含工艺/菌株词=0.6，泛称=0.3。

    用户要求条目是『XX菌可XXX』形式，故含具体菌株名（拉丁学名
    或菌株编号如 CCFM1445/BB-12/Nissle 1917）的条目得分最高。
    """
    t = it.get("text", "") or it.get("title", "") or ""
    if LATIN_RE.search(t) or STRAIN_CODE_RE.search(t):
        return 1.0
    if any(k in t for k in SPECIFIC_KW):
        return 0.6
    return 0.3


def authority_score(it: dict) -> float:
    """来源权威性: 卫健委=1.0，食品伙伴网=0.6，其他=0.5。"""
    return {"nhc": 1.0, "foodmate": 0.6}.get(it.get("source", ""), 0.5)


def relevance_score(it: dict) -> float:
    """相关度: 标题命中益生菌关键词数 >=2 =1.0，1 个=0.7，0 个=0.4。"""
    t = it.get("title", "") or ""
    hits = sum(1 for k in RELEVANCE_KW if k in t)
    return 1.0 if hits >= 2 else (0.7 if hits == 1 else 0.4)


# ----------------------------------------------------------------------------
# OpenAlex 数据增强（期刊质量 + 被引热度），带缓存
# ----------------------------------------------------------------------------
def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def openalex_enrich(pmids: list[str]) -> dict:
    """按 PMID 批量查询 OpenAlex，返回 {pmid: {journal_score, cited_score}}。

    使用缓存（TTL=CACHE_TTL_DAYS），只查缓存外的 PMID。
    """
    cache = _load_cache()
    today = date.today().isoformat()
    todo = [p for p in pmids
            if p not in cache or cache[p].get("at", "") < today]
    result = {p: {"journal_score": _band_score(cache[p].get("journal"), JOURNAL_BANDS, 0.3),
                  "cited_score": _band_score(cache[p].get("cited"), CITED_BANDS, 0.15)}
              for p in pmids if p in cache and cache[p].get("at", "") >= today}

    if todo:
        try:
            filt = urllib.parse.quote("ids.pmid:" + "|".join(todo), safe="|:")
            url = ("https://api.openalex.org/works?filter=" + filt +
                   "&per-page=50&select=id,ids,doi,cited_by_count,primary_location")
            doc = json.loads(_get(url))
            works = doc.get("results", [])
            pmid_map = {}
            for w in works:
                p = (w.get("ids") or {}).get("pmid")
                if p:
                    # OpenAlex 的 pmid 是完整 URL，归一化为裸数字
                    pmid_map[str(p).rstrip("/").split("/")[-1]] = w
            # 收集期刊 source id，逐个查 2yr_mean_citedness（每天仅几个期刊，且缓存7天）
            src_ids = {w["primary_location"]["source"]["id"]
                       for w in works if w.get("primary_location", {}).get("source")}
            src_scores = {}
            for sid in src_ids:
                try:
                    # 从完整 URL 提取裸 id 如 S4210238104
                    bare = sid.rstrip("/").split("/")[-1]
                    s_url = (f"https://api.openalex.org/sources/{bare}"
                             f"?select=id,display_name,summary_stats")
                    s_doc = json.loads(_get(s_url))
                    src_scores[sid] = (s_doc.get("summary_stats") or {}).get("2yr_mean_citedness")
                except Exception as e:  # noqa: BLE001
                    log.warning("OpenAlex 期刊查询失败 %s: %s", sid, e)
            for p, w in pmid_map.items():
                src_id = (w.get("primary_location") or {}).get("source", {}).get("id")
                jm = src_scores.get(src_id)
                cited = w.get("cited_by_count")
                cache[p] = {
                    "journal": jm,
                    "cited": cited,
                    "at": today,
                }
                result[p] = {
                    "journal_score": _band_score(jm, JOURNAL_BANDS, 0.3),
                    "cited_score": _band_score(cited, CITED_BANDS, 0.15),
                }
        except Exception as e:  # noqa: BLE001 - OpenAlex 失败不阻塞流程
            log.warning("OpenAlex 查询失败: %s", e)
            for p in todo:
                result.setdefault(p, {"journal_score": 0.3, "cited_score": 0.15})
        _save_cache(cache)
    return result


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "probiotic-hotspot/1.0 (mailto:lab@example.com)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ----------------------------------------------------------------------------
# 对外主入口
# ----------------------------------------------------------------------------
def score_all(items: list[dict]) -> list[dict]:
    """为每条目计算 score(0-100) 与 score_detail(分项)，写入条目 dict。"""
    pmids = [it["pmid"] for it in items if it.get("pmid")]
    enrich = openalex_enrich(pmids) if pmids else {}
    for it in items:
        en = enrich.get(it.get("pmid"), {})
        tag = it.get("tag", "相关文献")
        w = SCORE_WEIGHTS.get(tag, SCORE_WEIGHTS["相关文献"])
        subs = {
            "freshness": freshness(it),
            "journal": en.get("journal_score", 0.3),
            "cited": en.get("cited_score", 0.15),
            "evidence": evidence_score(it),
            "focus": focus_score(it),
            "specificity": specificity_score(it),
            "authority": authority_score(it),
            "relevance": relevance_score(it),
        }
        used = {k: subs[k] for k in w}
        it["score_detail"] = {k: round(v, 2) for k, v in used.items()}
        it["score"] = round(sum(w[k] * subs[k] for k in w) * 100)
    return items
