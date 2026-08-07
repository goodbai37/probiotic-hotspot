#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
益生菌研发热点速览 - 每日自动更新脚本
=====================================
数据源（按稳定性排序）:
  1. PubMed E-utilities  : 研究文献（不限 RCT，含临床/机制/动物/体外/综述；拉摘要提取菌株名）
  2. 食品伙伴网新闻首页    : 法规动态 / 行业动态（国内可访问）
  3. 卫健委官网受理公示     : 法规动态（反爬 412 时自动跳过，不影响主流程）
流程:
  fetch 各源原始条目 -> efetch 拉摘要 -> Ollama(qwen3:8b-gpu) 提炼为
  "XX菌可XXX" 短句并归类（仅 相关文献 / 法规动态）
  -> 评分排序取前 10 条 -> 渲染 widget.html
用法:
  python3 update_hotspot.py            # 正常更新
  python3 update_hotspot.py --no-llm   # 跳过 LLM 提炼（降级：直接截断标题）
输出:
  widget.html   手机小组件页面（覆盖更新）
  data.json     每日条目存档（追加）
"""

import argparse
import json
import logging
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import scoring

# ----------------------------------------------------------------------------
# 常量与配置（参数均有注释说明）
# ----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
WIDGET_HTML = BASE_DIR / "widget.html"      # 输出的小组件页面
ARCHIVE_HTML = BASE_DIR / "archive.html"    # 历史存档页
DATA_JSON = BASE_DIR / "data.json"          # 条目存档
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "qwen3:8b-gpu"               # 本地提炼模型（GPU 加速）
LOOKBACK_DAYS = 7                           # PubMed 回看窗口（天）
MAX_ITEMS = 10                              # 小组件一屏条数（10 条）
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# 关注方向关键词（骨骼/视力/女性健康/护肝/肠道/儿童），用于 PubMed 检索
FOCUS_TERMS = (
    "intestinal barrier OR gut permeability OR bone OR vision OR myopia "
    "OR vaginal OR vulvovaginal OR liver OR hepatic OR children OR pediatric OR infant"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hotspot")


# ----------------------------------------------------------------------------
# HTTP 工具
# ----------------------------------------------------------------------------
def fetch_url(url: str, timeout: int = 20, retries: int = 2) -> str:
    """GET 请求并返回文本；失败重试，最终抛异常。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            for enc in ("utf-8", "gbk", "latin-1"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except Exception as e:  # noqa: BLE001 - 各源失败都容错重试
            last_err = e
            log.warning("fetch fail(%s) %s -> %s", i + 1, url, e)
    raise RuntimeError(f"fetch failed: {url} -> {last_err}")


def fetch_url_safe(url: str, timeout: int = 20) -> str | None:
    """安全版：失败返回 None，不抛异常（用于可跳过源）。"""
    try:
        return fetch_url(url, timeout=timeout, retries=0)
    except Exception:
        return None


# ----------------------------------------------------------------------------
# 数据源 1: PubMed E-utilities
# ----------------------------------------------------------------------------
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def pubmed_search(term: str, mindate: str, maxdate: str, retmax: int = 20) -> list[str]:
    """esearch: 返回 PMID 列表（按最新日期排序）。"""
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "retmode": "json", "retmax": retmax,
        "sort": "date", "datetype": "edat", "mindate": mindate, "maxdate": maxdate,
    })
    doc = json.loads(fetch_url(f"{EUTILS}/esearch.fcgi?{q}"))
    return doc.get("esearchresult", {}).get("idlist", [])


MONTHS = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
          "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
          "nov": "11", "dec": "12"}


def parse_date(s: str) -> str:
    """把各种日期格式规范化为 YYYY-MM-DD，供排序用；无法解析则返回空串。
    支持: YYYY / YYYY Mon / YYYY Mon D / YYYY-MM-DD / YYYY/MM/DD"""
    s = (s or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{4})/(\d{2})/(\d{2})$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})\s+([A-Za-z]{3})\s*(\d{1,2})?$", s)
    if m:
        mon = MONTHS.get(m.group(2).lower())
        day = (m.group(3) or "01").zfill(2)
        return f"{m.group(1)}-{mon}-{day}" if mon else ""
    m = re.match(r"^(\d{4})$", s)
    return f"{m.group(1)}-01-01" if m else ""


def pubmed_summary(pmids: list[str]) -> list[dict]:
    """esummary: PMID -> 元数据（标题/期刊/日期/DOI）。"""
    if not pmids:
        return []
    q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids), "retmode": "json"})
    doc = json.loads(fetch_url(f"{EUTILS}/esummary.fcgi?{q}"))
    out = []
    for pid in pmids:
        r = doc.get("result", {}).get(pid)
        if not r:
            continue
        # 提取 DOI（ArticleIds 中 type=doi）
        doi = ""
        for aid in r.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
                break
        out.append({
            "title": re.sub(r"\s+", " ", r.get("title", "")).strip(),
            "journal": r.get("fulljournalname", "") or r.get("source", ""),
            # 优先电子出版日期（epubdate），回退印刷日期；两者都缺则空
            "date": parse_date(r.get("epubdate", "") or r.get("pubdate", "") or ""),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "doi": doi,
            "source": "pubmed",
            "pmid": pid,
            "pubtype": r.get("pubtype", []) or [],
            "abstract": "",  # 由 pubmed_abstracts 填充
        })
    return out


def pubmed_abstracts(pmids: list[str]) -> dict[str, str]:
    """efetch: PMID -> 摘要文本（前 3000 字符，覆盖绝大多数完整摘要），
    供 LLM 提取菌株名/结论。注意: 不能截太短，否则摘要结论部分(Results/Conclusions)
    被截掉，LLM 只能凭背景猜结论导致幻觉(如把淀粉酶工程研究编造成"促进骨生长")。"""
    if not pmids:
        return {}
    import xml.etree.ElementTree as ET
    q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"})
    try:
        xml = fetch_url(f"{EUTILS}/efetch.fcgi?{q}", timeout=60)
    except Exception as e:
        log.warning("efetch 失败: %s", e)
        return {}
    out = {}
    try:
        root = ET.fromstring(xml)
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//PMID")
            if not pmid:
                continue
            # 收集 AbstractText 的完整文本（含子标签）
            parts = ["".join(t.itertext()) for t in art.iter("AbstractText")]
            txt = re.sub(r"\s+", " ", " ".join(parts)).strip()
            out[pmid] = txt[:3000]
    except Exception as e:
        log.warning("efetch XML 解析失败: %s", e)
    return out


def fetch_pubmed() -> list[dict]:
    """近 LOOKBACK_DAYS 天的益生菌研究文献（不限 RCT，含机制/动物/体外/综述）。"""
    today = date.today()
    md = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y/%m/%d")
    mx = today.strftime("%Y/%m/%d")
    items = []
    # 路线 A: 益生菌研究文献（关注方向；不限 RCT）
    term_a = f"probiotics AND ({FOCUS_TERMS})"
    for it in pubmed_summary(pubmed_search(term_a, md, mx, retmax=40)):
        it["src_key"] = "pubmed_clinical"
        items.append(it)
    # 去重
    seen, uniq = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(it)
    # 拉取摘要（供 LLM 提取菌株名/具体功能）
    ab = pubmed_abstracts([it["pmid"] for it in uniq if it.get("pmid")])
    for it in uniq:
        it["abstract"] = ab.get(it.get("pmid", ""), "")
    log.info("PubMed 命中 %d 条", len(uniq))
    return uniq


# ----------------------------------------------------------------------------
# 数据源 2: 食品伙伴网（法规/行业/专利新闻）
# ----------------------------------------------------------------------------
FOODMATE_KEYWORDS = (
    "益生菌", "菌株", "微生态", "后生元", "肠道", "新食品原料",
    "卫健委", "受理", "专利", "保健食品", "乳杆菌", "双歧杆菌",
)


# 详情页发布时间正则: 页面含 "时间：2026-08-06 08:27" 或 "时间:2026-08-06"
_FOODMATE_DATE_RES = (
    re.compile(r"时间[：:]\s*(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日)"),
)


def _foodmate_pub_date(url: str) -> str:
    """抓详情页解析真实发布日期；失败回退今天。

    之前直接用 date.today()，导致跨天抓取（如 8.6 发布的文章在 8.7 抓取）
    被标成抓取日，用户反馈日期不准。现改为解析页面『时间：YYYY-MM-DD』。
    """
    try:
        html = fetch_url_safe(url, timeout=8)
        if html:
            for rx in _FOODMATE_DATE_RES:
                m = rx.search(html)
                if m:
                    d = m.group(1)
                    # 中文格式转 ISO: 2026年8月6日 -> 2026-08-06
                    if "年" in d:
                        parts = re.findall(r"\d{4}|\d{1,2}", d)
                        if len(parts) == 3:
                            d = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                    return d
    except Exception as e:
        log.debug("详情页日期解析失败 %s -> %s", url, e)
    return str(date.today())


def fetch_foodmate() -> list[dict]:
    """首页资讯列表 -> 过滤益生菌/法规/专利相关条目（按 URL 去重）。

    日期改为抓详情页解析真实发布日期（而非抓取当日），
    避免跨天抓取导致日期偏移。
    """
    html = fetch_url_safe("https://news.foodmate.net/")
    if not html:
        log.warning("食品伙伴网不可用，跳过")
        return []
    items, seen = [], set()
    # 匹配: <a href="https://news.foodmate.net/YYYY/MM/NNNN.html" ...>标题</a>
    for m in re.finditer(r'<a href="(https://news\.foodmate\.net/\d{4}/\d{2}/\d+\.html)"[^>]*>(.*?)</a>', html, re.S):
        url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not title or "title=" in title or url in seen:
            continue
        if any(k in title for k in FOODMATE_KEYWORDS):
            seen.add(url)
            items.append({
                "title": title,
                "url": url,
                "date": _foodmate_pub_date(url),  # 真实发布日期
                "source": "foodmate",
                "journal": "食品伙伴网",
                "doi": "",
                "abstract": "",
            })
    log.info("食品伙伴网命中 %d 条", len(items))
    return items


# ----------------------------------------------------------------------------
# 数据源 3: 卫健委新食品原料受理公示（反爬时静默跳过）
# ----------------------------------------------------------------------------
def fetch_nhc() -> list[dict]:
    """卫健委"新食品原料"受理公示列表；412/超时返回空。"""
    html = fetch_url_safe("https://www.nhc.gov.cn/sps/s7891/list.shtml")
    if not html:
        return []
    items = []
    for m in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"', html):
        url, title = m.group(1), m.group(2).strip()
        if "受理" in title or "新食品原料" in title:
            items.append({
                "title": title, "url": url, "date": str(date.today()),
                "source": "nhc", "journal": "国家卫健委", "doi": "", "abstract": "",
            })
    log.info("卫健委命中 %d 条", len(items))
    return items


# ----------------------------------------------------------------------------
# LLM 提炼: 原文标题 -> "XX菌可XXX" 短句 + 标签
# ----------------------------------------------------------------------------
TAGS = ("相关文献", "法规动态")

# 具体菌株名正则: 拉丁学名(双词) 或 菌株编号(如 CCFM1445/BB-12/Nissle 1917/LGG/Jlus66/MMX)
# 注意: 不能用 \b（中文环境下边界失效），用显式匹配
STRAIN_RE = re.compile(
    r"[A-Z][a-z]{2,}\s+[a-z]{3,}(?:\s+subsp\.\s+[A-Z][a-z]+)?"   # 拉丁双词学名
    r"|(?:CCFM\d+|BB-?12|LGG|Nissle\s*1917|"                      # 已知菌株编号
    r"[A-Z][a-z]{2,}\d{2,}|[A-Z]{2,}\d{2,}|[A-Z]{2,5})"          # 学名+编号/大写编号/缩写
)


def has_strain(it: dict) -> bool:
    """短句中是否含具体菌株名（拉丁学名或菌株编号）。"""
    return bool(STRAIN_RE.search(it.get("text", "")))


def smart_abst(abst: str, limit: int = 1000) -> str:
    """智能截断摘要: 保留头部(背景/菌株名) + 尾部(Results/Conclusions)。
    全文注入会让 prompt 过长导致 LLM 输出漂移；只截头部又会丢掉结论
    导致模型靠背景猜功效而编造。首尾拼接两全。"""
    if len(abst) <= limit:
        return abst
    head = abst[:400]
    tail = abst[-limit + 400:]
    return head + " …… " + tail


def llm_refine(items: list[dict]) -> list[dict]:
    """用本地 Ollama 把每条提炼为具体短句并归类。

    提示词要求严格输出 `0|短句|标签` 格式（0=不收录,1=收录），
    便于解析；`think:false` 关闭 qwen3 思考模式以提速。
    每条附带来源提示，帮助 LLM 正确分类。
    分批调用（每批 BATCH 条），避免上下文过长导致模型输出漂移。
    """
    if not items:
        return []
    src_hint = {
        "pubmed_clinical": "来源: PubMed 期刊文献(临床/机制/动物/体外研究)",
        "foodmate": "来源: 食品行业新闻(监管/法规/企业动态)",
        "nhc": "来源: 卫健委受理公示",
    }
    prompt_head = (
        "你是益生菌研发情报编辑。下面每行是一条新闻，含来源提示和摘要。行号从1开始。\n"
        "标签只有两类: 相关文献 / 法规动态。\n"
        "分类规则(看内容，不要按来源分类): \n"
        "  益生菌作用/机制/临床/动物/细胞/综述等研究文献→相关文献；\n"
        "  监管政策/受理公示/公告/法规/行业趋势→法规动态。\n"
        "收录标准: 近期发表的益生菌相关研究（介绍菌株作用/机制/功效，无论人体/动物/体外，不限RCT）都应收录归相关文献；\n"
        "监管政策与行业趋势新闻即使无具体菌株名也应收录（归法规动态）；与益生菌无关则0。\n"
        "不收录(标0): 未涉及益生菌/菌株干预的纯肠道菌群观察性研究、万古霉素等抗生素研究、\n"
        "粪菌移植研究、农药/兽药/普通食品研究。\n"
        "⚠️ 最关键的防编造规则: 短句必须严格基于摘要中的结果/结论，禁止编造摘要中没有的作用。\n"
        "  - 先通读完整摘要，找到 Results/Conclusion 里该菌株真正被验证的作用；\n"
        "  - 若研究主题是酶工程/食品加工/淀粉改性/材料/代谢产物提纯等，即使标题或摘要中出现菌株名，\n"
        "    也不是益生菌功效研究→必须标0；\n"
        "  - 若摘要通篇没有明确结论（如纯方法学、纯测序描述），标0；\n"
        "  - 摘要中有作用但未验证菌株功效时，如实写摘要所述内容，不要夸大。\n"
        "  - 粪菌移植(FMT)、粪便微生物群移植研究→即使提到益生菌也标0。\n"
        "输出语言: 短句必须用中文（菌株拉丁学名可保留），禁止输出英文句子。\n"
        "短句要求: 相关文献的短句必须包含菌株信息，格式为『菌株名+可/改善/促进等动词+具体作用』，\n"
        "如『鼠李糖乳杆菌GG可降低肠道通透性』、『植物乳杆菌Probio87改善便秘症状』。\n"
        "菌株名优先从标题提取，标题没有时从摘要中找：\n"
        "  - 标题/摘要有具体菌株（拉丁学名或编号）→ 必须写菌株名；\n"
        "  - 只有属级名称（乳杆菌/双歧杆菌/芽孢杆菌）→ 写属名+作用；\n"
        "  - 确实只有泛称『益生菌』→ 写『益生菌+作用』，不要标0；\n"
        "  - 只有与益生菌完全无关的条目（万古霉素、粪菌移植、纯肠道菌群观察、农药）→ 标0。\n"
        "法规动态的短句写具体政策/事件，如『新食品原料受理公示更新』。\n"
        "对每条输出一行，格式严格为: PMID|1或0|不超过22字的凝练短句|标签\n"
        "PMID 必须从输入新闻列表中原样抄取，这是链接回原文的关键，禁止编造或写错！\n"
        "禁止输出任何解释、标题、空行、序号以外的文字，严格按行输出结果。\n"
        "=== 新闻列表 ==="
    )
    BATCH = 5
    refined = []
    # 法规/新闻类（foodmate/nhc）不送 LLM：无摘要且短句易错位，改用标题截断+关键词兜底
    llm_items = [it for it in items if it.get("source") == "pubmed"]
    for start in range(0, len(llm_items), BATCH):
        batch = llm_items[start:start + BATCH]
        prompt = prompt_head
        for j, it in enumerate(batch, 1):
            hint = src_hint.get(it.get("src_key", ""), "")
            title = it["title"]
            # 智能截断摘要: 头部(菌株名) + 尾部(Results/结论)，共约 1000 字符。
            # 只给头部会丢结论导致编造功效；全文注入会因 prompt 过长导致输出漂移。
            abst = smart_abst(it.get("abstract") or "")
            pmid = it.get("pmid") or it["url"].rstrip("/").split("/")[-1]
            prompt += f"\n{j}. PMID={pmid} [{hint}] 标题: {title}"
            if abst:
                prompt += f" 摘要: {abst}"
        body = json.dumps({
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2},
        }).encode()
        req = urllib.request.Request(OLLAMA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                doc = json.loads(resp.read())
            content = doc.get("message", {}).get("content", "")
        except Exception as e:
            log.warning("Ollama 调用失败，降级为标题截断: %s", e)
            refined += [dict(it, text=it["title"][:26], tag="相关文献")
                        for it in items[:MAX_ITEMS]]
            break

        for line in content.splitlines():
            # 新格式: PMID|1或0|短句|标签 (PMID 优先); 兼容旧格式: 行号|1或0|短句|标签
            m = re.match(r"^\s*(\d+)\s*\|\s*([01])\s*\|\s*(.+?)\s*\|\s*(\S+)\s*$", line)
            if not m:
                continue
            first, keep, text, tag = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
            if keep != "1" or tag not in TAGS:
                continue
            # 优先按 PMID 精确映射（LLM 输出行号不可靠，会跳行/重排导致 URL 错位）
            hit = next((it for it in batch if str(it.get("pmid")) == first), None)
            if hit is None:
                idx = int(first)
                if not (1 <= idx <= len(batch)):
                    continue
                hit = batch[idx - 1]
            refined.append(dict(hit, text=text, tag=tag))
    log.info("LLM 提炼后收录 %d 条", len(refined))
    # 防错位校验: 短句里的菌株拉丁名/关键实体必须出现在对应条目的标题或摘要中，
    # 否则说明 LLM 行号/PMID 错位，剔除。这保证『短句↔链接』一一对应。
    def _aligned(it) -> bool:
        text = it["text"]
        title = (it.get("title") or "").lower()
        abst = (it.get("abstract") or "").lower()
        # 提取短句中的拉丁词（≥4字母），须在标题或摘要中出现
        latins = [w for w in re.findall(r"[A-Za-z]{4,}", text) if w.lower() not in ("fmt",)]
        if not latins:
            return True  # 纯中文短句无法校验，放行
        return all(w.lower() in (title + " " + abst) for w in latins)

    before = len(refined)
    refined = [it for it in refined if _aligned(it)]
    if len(refined) < before:
        log.info("防错位校验剔除 %d 条(短句与链接内容不符)", before - len(refined))
    # 后置过滤: 剔除英文短句(LLM 偶发输出英文)与 FMT/粪菌移植内容(规则要求标0)
    EN_RE = re.compile(r"[A-Za-z]{4,}")
    before = len(refined)
    refined = [
        it for it in refined
        if not (EN_RE.search(it["text"]) and not re.search(r"[\u4e00-\u9fff]", it["text"]))
        and not re.search(r"FMT|粪菌|粪便微生物", it["text"], re.I)
    ]
    if len(refined) < before:
        log.info("后置过滤剔除 %d 条(英文短句/FMT)", before - len(refined))
    # 法规保底: foodmate/nhc 的益生菌相关新闻直接收录为法规动态（标题截断）
    REG_KW = ("益生菌", "微生态", "后生元", "新食品原料", "保健食品", "乳杆菌", "双歧杆菌")
    existing_keys = {(it.get("url"), it.get("tag")) for it in refined}
    for it in items:
        if it.get("source") not in ("foodmate", "nhc"):
            continue
        if (it["url"], "法规动态") in existing_keys:
            continue
        if any(k in it["title"] for k in REG_KW):
            refined.append(dict(it, text=it["title"][:22], tag="法规动态"))
            existing_keys.add((it["url"], "法规动态"))
    # 短句去重（同一短句+同标签只留最高分候选，此处按原文顺序保留首个）
    seen_text, uniq = set(), []
    for it in refined:
        key = (it.get("tag"), it.get("text", ""))
        if key in seen_text:
            continue
        seen_text.add(key)
        uniq.append(it)
    log.info("法规保底+去重后 %d 条", len(uniq))
    # 不做类别保底: 某类当天没有合格内容就不展示（用户要求）
    return uniq


# ----------------------------------------------------------------------------
# 条目选择: 评分降序 + 菌株名优先
# ----------------------------------------------------------------------------
def pick_top(items: list[dict], max_items: int = MAX_ITEMS) -> list[dict]:
    """按评分降序取前 max_items 条。

    含具体菌株名的条目优先（评分相同或相近时排前），
    确保用户要求的『具体菌株』条目不被泛称条目挤掉。
    不做类别配额/多样性强制：某类当天没有合格内容就不显示。
    """
    items.sort(key=lambda x: (has_strain(x), x.get("score", 0)), reverse=True)
    return items[:max_items]


# ----------------------------------------------------------------------------
# HTML 渲染
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# HTML 渲染
# ----------------------------------------------------------------------------
TAG_CLS = {"相关文献": "t-clinical", "法规动态": "t-regulatory",
           "菌株专利": "t-patent", "工艺进展": "t-process"}
# 组顺序: 相关文献在前，法规动态在后
GROUP_ORDER = {"相关文献": 0, "法规动态": 1}

# 公共卡片样式（主卡片 + 存档页共用）
WIDGET_CSS = """
  :root{
    --bg:#eef3ee; --card:#fff; --ink:#1a2b22; --ink-2:#6b7a70; --line:#eef2ee;
    --green:#1f9d61; --blue:#2563eb; --amber:#d97706; --violet:#7c3aed; --teal:#0d9488;
    --radius:24px;
  }
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;-webkit-user-select:none;user-select:none}
  html,body{height:100%}
  body{
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","HarmonyOS Sans SC","MiSans","Microsoft YaHei",sans-serif;
    background:var(--bg);display:flex;justify-content:center;align-items:flex-start;
    padding:calc(16px + env(safe-area-inset-top)) 12px env(safe-area-inset-bottom);min-height:100vh;
  }
  .widget{
    width:100%;max-width:360px;background:var(--card);border-radius:var(--radius);
    box-shadow:0 8px 24px rgba(20,60,40,.10),0 2px 6px rgba(20,60,40,.06);
    padding:18px 14px 13px;
  }
  .head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
  .head .title{font-size:16px;font-weight:700;color:var(--ink);letter-spacing:.5px}
  .head .title::before{content:"";display:inline-block;width:6px;height:15px;border-radius:3px;background:var(--green);margin-right:7px;vertical-align:-2px}
  .head .meta{font-size:11px;color:var(--ink-2);display:flex;align-items:center;gap:4px}
  .head .meta .dot{width:7px;height:7px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .list{display:flex;flex-direction:column;gap:8px}
  .group-title{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:700;color:var(--ink-2);margin:12px 0 2px;letter-spacing:.3px}
  .group-title::before{content:"";width:4px;height:11px;border-radius:2px;background:var(--blue)}
  .group-title.g-regulatory::before{background:var(--amber)}
  .group-title .cnt{font-size:10px;font-weight:500;color:#a8bbad}
  .item{
    display:flex;align-items:center;gap:9px;background:#f7faf7;border:1px solid var(--line);
    border-radius:14px;padding:11px 12px;min-height:44px;text-decoration:none;
    transition:transform .12s ease,background .12s ease;
  }
  .item:active{transform:scale(.975);background:#eef6ef}
  .tag{flex-shrink:0;font-size:10px;line-height:1;font-weight:600;padding:5px 7px;border-radius:999px;white-space:nowrap}
  .t-clinical{color:var(--blue);background:rgba(37,99,235,.10)}
  .t-regulatory{color:var(--amber);background:rgba(217,119,6,.10)}
  .t-patent{color:var(--violet);background:rgba(124,58,237,.10)}
  .t-process{color:var(--teal);background:rgba(13,148,136,.10)}
  .item .txtwrap{flex:1;display:flex;flex-direction:column;gap:2px;min-width:0}
  .item .txt{font-size:12.5px;line-height:1.4;color:var(--ink);font-weight:500}
  .item .sub{font-size:10px;color:#a3b5a8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .item .score{flex-shrink:0;font-size:10px;color:#93a89a;font-weight:600}
  .item .arrow{flex-shrink:0;color:#9db3a6;font-size:14px}
  .item.extra{display:none}
  .widget.expanded .item.extra{display:flex}
  .expand{margin-top:10px;text-align:center}
  .expand button{
    width:100%;padding:9px 0;font-size:12px;font-weight:600;color:var(--green);
    background:#f0f7f2;border:1px solid var(--line);border-radius:12px;cursor:pointer;
    transition:background .12s ease;
  }
  .expand button:active{background:#e4f1e8}
  .widget.expanded .expand{display:none}
  .foot{margin-top:12px;padding-top:9px;border-top:1px dashed var(--line);display:flex;justify-content:space-between;align-items:center}
  .foot .updated{font-size:10px;color:var(--ink-2)}
  .foot .more{font-size:11px;color:var(--green);font-weight:600;text-decoration:none}
"""

# 存档页附加样式
ARCH_CSS = """
  .arch .day{font-size:12px;font-weight:700;color:var(--ink);margin:14px 0 2px;padding-top:10px;border-top:1px dashed var(--line)}
  .arch .day:first-of-type{border-top:none}
  .arch .back{display:inline-block;font-size:11px;color:var(--green);font-weight:600;text-decoration:none;margin-bottom:10px}
  .arch .note{font-size:10px;color:var(--ink-2);margin:2px 0 6px}
"""


def _group_items(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """按标签分组，组内按分数降序。组顺序固定: 相关文献 → 法规动态。"""
    groups: dict[str, list[dict]] = {}
    for it in items:
        tag = TAG_ALIAS.get(it["tag"], it["tag"])
        groups.setdefault(tag, []).append(it)
    for g in groups.values():
        g.sort(key=lambda x: x.get("score", 0), reverse=True)
    return sorted(groups.items(), key=lambda kv: GROUP_ORDER.get(kv[0], 99))


TAG_ALIAS = {"临床文献": "相关文献"}  # 旧数据归一化


FOLD_PER_GROUP = 2  # 折叠态每组显示条数，超出部分点"展开全部"后显示


def _item_html(it: dict, extra: bool = False) -> str:
    tag = TAG_ALIAS.get(it["tag"], it["tag"])
    cls = TAG_CLS.get(tag, "t-clinical")
    extra_cls = " extra" if extra else ""
    # 副行: 期刊 · 日期（缺失时省略对应段）
    journal = (it.get("journal") or "").strip()
    pdate = (it.get("date") or "").strip()
    sub = " · ".join(x for x in (journal, pdate) if x)
    sub_html = f'      <span class="sub">{sub}</span>\n' if sub else ""
    return (
        f'    <a class="item{extra_cls}" href="{it["url"]}" title="{it.get("title", "")}">\n'
        f'      <span class="tag {cls}">{tag}</span>\n'
        f'      <span class="txtwrap">\n'
        f'        <span class="txt">{it["text"]}</span>\n'
        f'{sub_html}'
        f'      </span>\n'
        f'      <span class="score">{it.get("score", "")}</span>\n'
        f'      <span class="arrow">›</span>\n'
        f'    </a>'
    )


def _group_html(groups: list[tuple[str, list[dict]]], fold: bool = False) -> str:
    """渲染分类分组列表（组标题 + 组内条目）。fold=True 时每组只显示前 FOLD_PER_GROUP 条。"""
    rows = []
    for tag, items in groups:
        gcls = "g-regulatory" if tag == "法规动态" else ""
        rows.append(
            f'    <div class="group-title {gcls}">{tag}<span class="cnt">{len(items)} 条</span></div>'
        )
        for idx, it in enumerate(items):
            rows.append(_item_html(it, extra=fold and idx >= FOLD_PER_GROUP))
    return "\n".join(rows)


def render_html(items: list[dict], updated: str) -> str:
    """渲染小组件页面：折叠态只占一小块（每组前 FOLD_PER_GROUP 条），
    点"展开全部"后完整列出全部条目，整页可滑动。"""
    groups = _group_items(items)
    body = _group_html(groups, fold=True)
    total = len(items)
    folded = sum(max(0, len(g) - FOLD_PER_GROUP) for _, g in groups)
    btn_text = f"展开剩余 {folded} 条 ›" if folded > 0 else f"展开全部 {total} 条 ›"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1f9d61">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="益生菌热点">
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>益生菌研发热点速览</title>
<style>{WIDGET_CSS}</style>
</head>
<body>
<div class="widget" id="widget">
  <div class="head">
    <div class="title">益生菌研发热点速览</div>
    <div class="meta"><span class="dot"></span>{updated}</div>
  </div>
  <div class="list">
{body}
  </div>
  <div class="expand">
    <button id="expandBtn" type="button">{btn_text}</button>
  </div>
  <div class="foot">
    <span class="updated">更新于 {updated} · {total} 条</span>
    <a class="more" href="archive.html">更多 ›</a>
  </div>
</div>
<script>
  document.getElementById('expandBtn').addEventListener('click', function () {{
    document.getElementById('widget').classList.add('expanded');
  }});
</script>
<script>
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/sw.js').catch(() => {{}});
  }}
</script>
</body>
</html>
"""


def render_archive(records: list[dict]) -> str:
    """渲染历史存档页（日期倒序，每日内按分类分组、组内按分数排序）。"""
    days = []
    for rec in sorted(records, key=lambda r: r["date"], reverse=True):
        items = rec.get("items", [])
        total = len(items)
        days.append(f'    <div class="day">{rec["date"]} · {total} 条</div>')
        days.append(_group_html(_group_items(items)))
    body = "\n".join(days)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1f9d61">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="益生菌热点">
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">
<link rel="apple-touch-icon" href="/icon-192.png">
<title>益生菌研发热点 · 历史存档</title>
<style>{WIDGET_CSS}{ARCH_CSS}</style>
</head>
<body>
<div class="widget arch">
  <div class="head">
    <div class="title">历史存档</div>
    <div class="meta"><span class="dot"></span>{len(records)} 天 · {sum(len(r.get('items', [])) for r in records)} 条</div>
  </div>
  <a class="back" href="widget.html">‹ 返回今日热点</a>
  <div class="note">每日 Top {MAX_ITEMS} 条 · 点击条目查看原始来源</div>
  <div class="list">
{body}
  </div>
</div>
</body>
</html>"""
    js = """
<script>
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
</script>"""
    return html + js


# ----------------------------------------------------------------------------
# 移动组件渲染（probiotic-hotspot-mobile.html）
# ----------------------------------------------------------------------------
MOBILE_HTML = BASE_DIR / "probiotic-hotspot-mobile.html"
MOBILE_FOLD = 2  # 每组默认显示条数

MOBILE_CSS = """
.probiotic-hotspot-mobile {
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'HarmonyOS Sans SC', 'MiSans', 'Microsoft YaHei', sans-serif;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(20, 60, 40, 0.08);
  overflow: hidden;
  margin: 12px;
}
.hs-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 16px 12px; border-bottom: 1px solid #f0f5f0; }
.hs-title { font-size: 18px; font-weight: 700; color: #1a2b22; margin: 0; }
.hs-update { font-size: 12px; color: #6b7a70; background: #f0f7f2; padding: 4px 8px; border-radius: 12px; }
.hs-group { border-bottom: 1px solid #f5f8f5; }
.hs-group-header { display: flex; align-items: center; padding: 12px 16px; cursor: pointer; }
.hs-group-dot { width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }
.hs-clinical .hs-group-dot { background: #2563eb; }
.hs-regulatory .hs-group-dot { background: #d97706; }
.hs-group-title { font-size: 14px; font-weight: 600; color: #1a2b22; flex: 1; }
.hs-group-count { font-size: 12px; color: #a8bbad; margin-right: 8px; }
.hs-group-content { display: flex; flex-direction: column; }
.hs-item { display: flex; align-items: flex-start; padding: 12px 16px; text-decoration: none; border-bottom: 1px solid #f8faf8; transition: background 0.1s ease; }
.hs-item:active { background: #f7faf7; }
.hs-item-extra { display: none; }
.hs-group.expanded .hs-item-extra { display: flex; }
.hs-item-tag { flex-shrink: 0; font-size: 10px; font-weight: 600; padding: 4px 6px; border-radius: 999px; margin-right: 8px; margin-top: 2px; }
.hs-tag-clinical { color: #2563eb; background: rgba(37, 99, 235, 0.1); }
.hs-tag-regulatory { color: #d97706; background: rgba(217, 119, 6, 0.1); }
.hs-item-content { flex: 1; min-width: 0; }
.hs-item-text { font-size: 14px; line-height: 1.4; color: #1a2b22; font-weight: 500; margin: 0 0 4px 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.hs-item-meta { font-size: 11px; color: #a3b5a8; margin: 0; }
.hs-expand-btn { font-size: 12px; color: #6b7a70; text-align: center; padding: 8px 0; cursor: pointer; display: none; }
.hs-group.expanded .hs-expand-btn { display: block; }
.hs-footer { padding: 16px; text-align: center; border-top: 1px solid #f0f5f0; }
.hs-more-link { font-size: 14px; font-weight: 600; color: #1f9d61; text-decoration: none; }
"""

MOBILE_JS = """
<script>
// 点击组头展开/收起
var groups = document.querySelectorAll('.hs-group-header');
for (var i = 0; i < groups.length; i++) {
  groups[i].addEventListener('click', function () {
    var group = this.closest('.hs-group');
    group.classList.toggle('expanded');
  });
}
</script>
"""


def _mobile_item_html(it: dict, extra: bool = False) -> str:
    tag = TAG_ALIAS.get(it["tag"], it["tag"])
    tag_cls = "hs-tag-clinical" if tag == "相关文献" else "hs-tag-regulatory"
    extra_cls = " hs-item-extra" if extra else ""
    journal = (it.get("journal") or "").strip()
    pdate = (it.get("date") or "").strip()
    meta = " · ".join(x for x in (journal, pdate) if x)
    return (
        f'      <a class="hs-item{extra_cls}" href="{it["url"]}" target="_blank">\n'
        f'        <span class="hs-item-tag {tag_cls}">{tag}</span>\n'
        f'        <div class="hs-item-content">\n'
        f'          <p class="hs-item-text">{it["text"]}</p>\n'
        f'          <p class="hs-item-meta">{meta}</p>\n'
        f'        </div>\n'
        f'      </a>'
    )


def render_mobile(items: list[dict], updated: str) -> str:
    """渲染移动端独立页面（完整 HTML + PWA，可直接添加到手机桌面）。

    结构与 widget.html 一致：相关文献/法规动态两类分组，组内按分数降序；
    每组默认显示前 MOBILE_FOLD 条，点击组头/展开按钮显示全部。
    """
    groups = _group_items(items)
    parts = [
        '<!DOCTYPE html>',
        '<html lang="zh-CN">',
        '<head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        '<meta name="theme-color" content="#1f9d61">',
        '<meta name="apple-mobile-web-app-capable" content="yes">',
        '<meta name="mobile-web-app-capable" content="yes">',
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
        '<meta name="apple-mobile-web-app-title" content="益生菌热点">',
        '<link rel="manifest" href="/manifest.json">',
        '<link rel="icon" type="image/png" sizes="192x192" href="/icon-192.png">',
        '<link rel="apple-touch-icon" href="/icon-192.png">',
        '<title>益生菌研发热点速览</title>',
        '<style>',
        '  html,body{margin:0;padding:0;background:#eef3ee}',
        '  body{display:flex;justify-content:center;padding:calc(12px + env(safe-area-inset-top)) 0 env(safe-area-inset-bottom);min-height:100vh}',
        '  .probiotic-hotspot-mobile{width:100%;max-width:560px}',
        MOBILE_CSS,
        '</style>',
        '</head>',
        '<body>',
        '<!-- Mobile component for probiotic hotspot - 自动生成 -->',
        '<div class="probiotic-hotspot-mobile">',
        '  <div class="hs-header">',
        '    <h2 class="hs-title">益生菌研发热点速览</h2>',
        f'    <span class="hs-update">{updated} 更新</span>',
        '  </div>',
    ]
    for tag, group in groups:
        gcls = "hs-clinical" if tag == "相关文献" else "hs-regulatory"
        parts.append(f'  <div class="hs-group {gcls}">')
        parts.append('    <div class="hs-group-header">')
        parts.append('      <span class="hs-group-dot"></span>')
        parts.append(f'      <span class="hs-group-title">{tag}</span>')
        parts.append(f'      <span class="hs-group-count">{len(group)} 条</span>')
        parts.append('    </div>')
        parts.append('    <div class="hs-group-content">')
        for idx, it in enumerate(group):
            parts.append(_mobile_item_html(it, extra=idx >= MOBILE_FOLD))
        parts.append('    </div>')
        folded = max(0, len(group) - MOBILE_FOLD)
        parts.append('    <div class="hs-expand-btn" onclick="this.closest(\'.hs-group\').classList.toggle(\'expanded\')">')
        parts.append(f'      展开剩余 {folded} 条 ›')
        parts.append('    </div>')
        parts.append('  </div>')
    parts.append('  <div class="hs-footer">')
    parts.append('    <a href="archive.html" class="hs-more-link">查看历史存档 ›</a>')
    parts.append('  </div>')
    parts.append('</div>')
    parts.append(MOBILE_JS)
    parts.append('<script>')
    parts.append("  if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js').catch(() => {}); }")
    parts.append('</script>')
    parts.append('</body>')
    parts.append('</html>')
    return '\n'.join(parts) + '\n'



def main() -> int:
    ap = argparse.ArgumentParser(description="益生菌研发热点每日更新")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM 提炼（标题截断降级）")
    args = ap.parse_args()

    # 1) 抓取各源
    items = fetch_pubmed()
    items += fetch_foodmate()
    items += fetch_nhc()
    for it in items:
        it.setdefault("src_key", "foodmate")
    if not items:
        log.error("所有数据源均无可用数据，保留旧页面")
        return 1

    # 2) 提炼与归类
    refined = items if args.no_llm else llm_refine(items)
    # no-llm 降级路径: 原始条目无 tag/text，按来源兜底打标签并截断标题为短句
    if args.no_llm:
        for it in refined:
            it.setdefault("tag", "相关文献" if it.get("source") == "pubmed" else "法规动态")
            it.setdefault("text", (it.get("title") or "")[:26])

    # 2.5) 热度评分（影响因子/被引/新鲜度/证据等级/方向匹配）
    refined = scoring.score_all(refined)

    # 3) 按评分精选 5 条
    top = pick_top(refined)
    if not top:
        log.error("筛选后无条目")
        return 1

    # 4) 渲染 + 存档
    today = date.today().isoformat()
    WIDGET_HTML.write_text(render_html(top, today), encoding="utf-8")
    MOBILE_HTML.write_text(render_mobile(top, today), encoding="utf-8")

    records = []
    if DATA_JSON.exists():
        try:
            records = json.loads(DATA_JSON.read_text(encoding="utf-8"))
        except Exception:
            records = []
    # 同一天只保留最新一次运行的结果（当天多次运行则覆盖）
    records = [r for r in records if r.get("date") != today]
    records.append({"date": today, "items": [
        {"text": it["text"], "tag": it["tag"], "url": it["url"], "source": it["source"],
         "journal": it.get("journal", ""), "date": it.get("date", ""),
         "score": it.get("score"), "score_detail": it.get("score_detail")}
        for it in top
    ]})
    DATA_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    ARCHIVE_HTML.write_text(render_archive(records), encoding="utf-8")

    log.info("完成: %d 条已写入 %s", len(top), WIDGET_HTML)
    for it in sorted(top, key=lambda x: x.get("score", 0), reverse=True):
        log.info("  [%s][%s分] %s -> %s", it["tag"], it.get("score", "-"), it["text"], it["url"])
        log.info("      分项: %s", it.get("score_detail", {}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
