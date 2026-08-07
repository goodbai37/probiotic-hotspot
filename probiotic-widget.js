// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: blue; icon-glyph: pills;
// ============================================================
// 益生菌热点速览 · 主屏幕小组件 + 滑动浏览 (Scriptable) v3
// 数据源: https://goodbai37.github.io/probiotic-hotspot/data.json
//
// 两种模式:
//   1) 主屏幕小组件: 简洁显示前 2-4 条, 点击标题/底部按钮
//      进入全屏滑动浏览 (scriptable:///run 打开 App 运行本脚本)
//   2) 运行模式 (Scriptable 里点 ▶ 或点小组件):
//      全屏左右滑动, 每页一张词条卡片, 不拥挤
//
// 更新: 每日 00:30 自动刷新
// ============================================================

const DATA_URL = "https://goodbai37.github.io/probiotic-hotspot/data.json";
const MAX_ITEMS = { small: 2, medium: 3, large: 4 }; // 小组件显示条数
const RUN_URL = "scriptable:///run?scriptName=probiotic-widget"; // 打开全屏滑动

// 配色 (深色模式自动适配)
const GREEN = Color.dynamic(new Color("#1f9d61"), new Color("#34d399"));
const BLUE = new Color("#2563eb");
const AMBER = new Color("#d97706");
const INK = Color.dynamic(new Color("#1a2b22"), new Color("#e5e7eb"));
const MUTED = Color.dynamic(new Color("#6b7a70"), new Color("#9ca3af"));
const CARD = Color.dynamic(new Color("#ffffff"), new Color("#1f2937"));
const BG = Color.dynamic(new Color("#eef3ee"), new Color("#111827"));
const TAG_BG_BLUE = Color.dynamic(new Color("#eaf4ef"), new Color("#123524"));
const TAG_BG_AMBER = Color.dynamic(new Color("#fdf3e3"), new Color("#3a2a0a"));

async function fetchLatest() {
  const req = new Request(DATA_URL);
  req.timeoutInterval = 15;
  const records = await req.loadJSON();
  if (!records || records.length === 0) throw new Error("data.json 为空");
  return records[records.length - 1]; // 最后一条 = 最新一天
}

// ---------- 小组件单行条目 ----------
function addItemRow(widget, item, showMeta) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  row.spacing = 6;
  row.url = item.url; // 点击整行打开原文

  const dot = row.addStack();
  dot.size = new Size(8, 8);
  dot.cornerRadius = 4;
  dot.backgroundColor = item.tag === "法规动态" ? AMBER : BLUE;

  const col = row.addStack();
  col.layoutVertically();
  col.spacing = 2;
  col.addSpacer(2);

  const title = col.addText(item.text || item.title || "");
  title.font = Font.mediumSystemFont(13);
  title.textColor = INK;
  title.lineLimit = 2;

  if (showMeta) {
    const meta = col.addText([item.journal, item.date].filter(Boolean).join(" · "));
    meta.font = Font.systemFont(10);
    meta.textColor = MUTED;
    meta.lineLimit = 1;
  }

  const score = row.addText(String(item.score ?? ""));
  score.font = Font.boldSystemFont(11);
  score.textColor = GREEN;
}

// ---------- 模式1: 主屏幕小组件 ----------
async function createWidget() {
  const widget = new ListWidget();
  widget.backgroundColor = CARD;
  widget.setPadding(14, 14, 12, 14);

  const family = config.widgetFamily || "medium";
  const limit = MAX_ITEMS[family] || 3;

  // 标题行: 点击进入全屏滑动浏览
  const head = widget.addStack();
  head.layoutHorizontally();
  head.centerAlignContent();
  head.spacing = 6;
  head.url = RUN_URL;
  const title = head.addText("🦠 益生菌热点");
  title.font = Font.boldSystemFont(16);
  title.textColor = INK;
  head.addSpacer();
  const date = head.addText("…");
  date.font = Font.semiboldSystemFont(11);
  date.textColor = MUTED;
  widget.addSpacer(8);

  try {
    const latest = await fetchLatest();
    date.text = latest.date || "";
    const items = (latest.items || []).slice(0, limit);
    const total = (latest.items || []).length;

    if (!items.length) {
      const empty = widget.addText("今日暂无数据");
      empty.font = Font.systemFont(13);
      empty.textColor = MUTED;
    } else {
      for (const it of items) {
        addItemRow(widget, it, family !== "small");
        widget.addSpacer(5);
      }
    }

    // 底部: 进入滑动浏览
    widget.addSpacer(2);
    const foot = widget.addStack();
    foot.layoutHorizontally();
    foot.centerAlignContent();
    foot.url = RUN_URL;
    const more = foot.addText(`滑动浏览全部 ${total} 条 ›`);
    more.font = Font.semiboldSystemFont(10);
    more.textColor = GREEN;
    foot.addSpacer();
    const tip = foot.addText("点标题/此处");
    tip.font = Font.systemFont(9);
    tip.textColor = MUTED;
  } catch (e) {
    date.text = "";
    widget.addSpacer(4);
    const err = widget.addText("⚠️ " + (e.message || "加载失败"));
    err.font = Font.mediumSystemFont(13);
    err.textColor = new Color("#dc2626");
    widget.addSpacer(2);
    const retry = widget.addText("长按小组件→编辑→点完成刷新");
    retry.font = Font.systemFont(9);
    retry.textColor = MUTED;
  }

  // 每日 00:30 自动刷新
  const next = new Date();
  next.setHours(0, 30, 0, 0);
  if (next <= new Date()) next.setDate(next.getDate() + 1);
  widget.refreshAfterDate = next;
  return widget;
}

// ---------- 模式2: 全屏左右滑动, 每页一个词条 ----------
async function createSlides() {
  const latest = await fetchLatest();
  const items = latest.items || [];
  const screen = Device.screenSize();
  // 卡片高度 = 屏幕高度 - 上下留白, 保证每页只放一张卡片
  const cardW = Math.min(screen.width - 48, 560);
  const cardH = screen.height - 180;

  const page = new Page();
  page.setBackgroundColor(BG);

  if (!items.length) {
    const s = page.addStack();
    const t = s.addText("今日暂无数据");
    t.font = Font.mediumSystemFont(16);
    t.textColor = MUTED;
  }

  for (const it of items) {
    const isReg = it.tag === "法规动态";

    const card = page.addStack();
    card.layoutVertically();
    card.size = new Size(cardW, cardH);
    card.backgroundColor = CARD;
    card.cornerRadius = 28;
    card.setPadding(28, 24, 24, 24);

    // 分类标签
    const tag = card.addText(isReg ? "⚖️ 法规动态" : "🔬 相关文献");
    tag.font = Font.boldSystemFont(13);
    tag.textColor = isReg ? AMBER : BLUE;
    card.addSpacer(14);

    // 大标题
    const t = card.addText(it.text || it.title || "");
    t.font = Font.boldSystemFont(26);
    t.textColor = INK;
    t.lineLimit = 6;
    card.addSpacer(16);

    // 期刊 · 日期
    const meta = card.addText([it.journal, it.date].filter(Boolean).join("  ·  "));
    meta.font = Font.mediumSystemFont(13);
    meta.textColor = MUTED;
    meta.lineLimit = 2;
    card.addSpacer(24);

    // 热度分数
    const scoreRow = card.addStack();
    scoreRow.layoutHorizontally();
    scoreRow.centerAlignContent();
    scoreRow.spacing = 8;
    const sl = scoreRow.addText("热度");
    sl.font = Font.mediumSystemFont(12);
    sl.textColor = MUTED;
    const sv = scoreRow.addText(String(it.score ?? "—"));
    sv.font = Font.boldSystemFont(20);
    sv.textColor = GREEN;
    card.addSpacer();

    // 查看原文按钮
    const btn = card.addButton("查看原文 →");
    btn.url = it.url;
    btn.backgroundColor = isReg ? TAG_BG_AMBER : TAG_BG_BLUE;
    btn.cornerRadius = 14;
    btn.font = Font.boldSystemFont(15);
    btn.textColor = isReg ? AMBER : GREEN;

    // 页码提示
    const idx = items.indexOf(it) + 1;
    const p = card.addText(`${idx} / ${items.length}  ·  左右滑动`);
    p.font = Font.systemFont(10);
    p.textColor = MUTED;
  }

  page.present(true); // 全屏
}

// ---------- 入口 ----------
const widget = await createWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
  Script.complete();
} else {
  // App 里运行 (点 ▶ 或点小组件进入): 展示全屏滑动
  try {
    await createSlides();
  } catch (e) {
    const p = new Page();
    p.setBackgroundColor(BG);
    const s = p.addStack();
    s.layoutVertically();
    s.centerAlignContent();
    const t = s.addText("⚠️ " + (e.message || "加载失败"));
    t.font = Font.boldSystemFont(16);
    t.textColor = new Color("#dc2626");
    p.present(true);
  }
}
