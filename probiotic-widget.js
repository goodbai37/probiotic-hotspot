// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: blue; icon-glyph: pills;
// ============================================================
// 益生菌热点速览 · 主屏幕小组件 + 滑动浏览 (Scriptable) v5
// 数据源: https://goodbai37.github.io/probiotic-hotspot/data.json
//
// 两种模式:
//   1) 主屏幕小组件: 简洁显示前 2-4 条, 点击标题/底部进入全屏浏览
//   2) 运行模式 (Scriptable 里点 ▶ 或点小组件):
//      用 WebView.loadURL 加载线上滑动页面 slides.html
//      (滑动界面由网页维护, 以后改版无需再更新脚本!)
//
// 更新: 每日 00:30 自动刷新
// ============================================================

const DATA_URL = "https://goodbai37.github.io/probiotic-hotspot/data.json";
const SLIDES_URL = "https://goodbai37.github.io/probiotic-hotspot/slides.html";
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

async function fetchLatest() {
  const req = new Request(DATA_URL);
  req.timeoutInterval = 15;
  const records = await req.loadJSON();
  if (!records || records.length === 0) throw new Error("data.json 为空");
  return records[records.length - 1]; // 最后一条 = 最新一天
}

// HTML 转义 (防止词条内容破坏页面结构)
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
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


async function presentSlides() {
  // 直接加载线上滑动页面 (界面更新无需改脚本)
  const wv = new WebView();
  // 允许本站资源 (页面本身+data.json), 外部链接交给 Safari
  wv.shouldAllowRequest = (req) => {
    const u = req.url || "";
    if (u.startsWith("https://goodbai37.github.io")) return true;
    if (u.startsWith("http")) {
      Safari.open(u);
      return false;
    }
    return true;
  };
  const screen = Device.screenSize();
  await wv.loadURL(SLIDES_URL, new Size(screen.width, screen.height), true);
}

// ---------- 入口 ----------
const widget = await createWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
  Script.complete();
} else {
  // App 里运行 (点 ▶ 或点小组件进入): 全屏滑动浏览
  try {
    await presentSlides();
  } catch (e) {
    const p = new Alert();
    p.title = "⚠️ 加载失败";
    p.message = String(e.message || e);
    p.addAction("好");
    await p.presentAlert();
  }
}
