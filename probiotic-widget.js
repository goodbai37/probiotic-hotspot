// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: blue; icon-glyph: pills;
// ============================================================
// 益生菌热点速览 · 主屏幕小组件 + 滑动浏览 (Scriptable) v4
// 数据源: https://goodbai37.github.io/probiotic-hotspot/data.json
//
// 两种模式:
//   1) 主屏幕小组件: 简洁显示前 2-4 条, 点击标题/底部进入全屏浏览
//   2) 运行模式 (Scriptable 里点 ▶ 或点小组件):
//      全屏左右滑动卡片, 每页一张词条 (WebView + scroll-snap,
//      兼容所有 Scriptable 版本, 不依赖新版 Page API)
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

// ---------- 模式2: 全屏左右滑动卡片 (WebView + scroll-snap) ----------
function buildSlidesHTML(items) {
  const cards = items.map((it, i) => {
    const isReg = it.tag === "法规动态";
    const tagText = isReg ? "⚖️ 法规动态" : "🔬 相关文献";
    const tagColor = isReg ? "#d97706" : "#2563eb";
    const tagBg = isReg ? "rgba(217,119,6,.12)" : "rgba(37,99,235,.10)";
    const title = esc(it.text || it.title || "");
    const meta = esc([it.journal, it.date].filter(Boolean).join("  ·  "));
    const score = esc(String(it.score ?? "—"));
    const url = esc(it.url || "#");
    const idx = i + 1;
    return `
      <a class="card" href="${url}">
        <div class="tag" style="color:${tagColor};background:${tagBg}">${tagText}</div>
        <div class="title">${title}</div>
        <div class="meta">${meta}</div>
        <div class="score-wrap">
          <span class="score-label">热度</span>
          <span class="score" style="color:${tagColor}">${score}</span>
        </div>
        <div class="open">查看原文 →</div>
        <div class="page">${idx} / ${items.length} · 左右滑动</div>
      </a>`;
  }).join("");

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<style>
  *{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{height:100%;overflow:hidden}
  body{
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","HarmonyOS Sans SC",sans-serif;
    background:#eef3ee;
  }
  @media (prefers-color-scheme:dark){
    body{background:#111827}
  }
  .track{
    display:flex;height:100%;overflow-x:auto;scroll-snap-type:x mandatory;
    -webkit-overflow-scrolling:touch;scrollbar-width:none;
  }
  .track::-webkit-scrollbar{display:none}
  .card{
    flex:0 0 100%;scroll-snap-align:center;scroll-snap-stop:always;
    display:flex;flex-direction:column;
    padding:calc(56px + env(safe-area-inset-top)) 36px calc(48px + env(safe-area-inset-bottom));
    text-decoration:none;color:#1a2b22;
  }
  @media (prefers-color-scheme:dark){.card{color:#e5e7eb}}
  .tag{
    align-self:flex-start;font-size:13px;font-weight:700;
    padding:6px 14px;border-radius:999px;margin-bottom:28px;
  }
  .title{font-size:28px;font-weight:800;line-height:1.4}
  .meta{font-size:14px;color:#6b7a70;margin-top:20px;line-height:1.5}
  @media (prefers-color-scheme:dark){.meta{color:#9ca3af}}
  .score-wrap{margin-top:auto;display:flex;align-items:baseline;gap:10px;padding-top:40px}
  .score-label{font-size:13px;color:#6b7a70}
  @media (prefers-color-scheme:dark){.score-label{color:#9ca3af}}
  .score{font-size:30px;font-weight:800}
  .open{
    margin-top:14px;text-align:center;font-size:16px;font-weight:700;
    padding:14px;border-radius:16px;color:#1f9d61;background:rgba(31,157,97,.10);
  }
  @media (prefers-color-scheme:dark){.open{color:#34d399}}
  .page{text-align:center;font-size:12px;color:#a8bbad;margin-top:18px}
</style>
</head>
<body>
  <div class="track">${cards}</div>
</body>
</html>`;
}

async function presentSlides() {
  const latest = await fetchLatest();
  const items = latest.items || [];
  if (!items.length) throw new Error("今日暂无数据");

  const wv = new WebView();
  // 点击卡片: 拦截请求, 用 Safari 打开原文 (避免 WebView 内导航)
  wv.shouldAllowRequest = (req) => {
    const u = req.url;
    if (u && u.startsWith("http")) {
      Safari.open(u);
      return false;
    }
    return true;
  };
  await wv.loadHTML(buildSlidesHTML(items), null, new Size(), true);
  await wv.present();
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
