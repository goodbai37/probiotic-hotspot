// Variables used by Scriptable.
// These must be at the very top of the file. Do not edit.
// icon-color: blue; icon-glyph: pills;
// ============================================================
// 益生菌热点速览 · 主屏幕小组件 (Scriptable) v2
// 数据源: https://goodbai37.github.io/probiotic-hotspot/data.json
// 尺寸: 小=3条 / 中=5条 / 大=8条, 点击条目直达原文
// 更新: 每日 00:30 自动刷新
// 修复: v2 改用 Script.setWidget 标准入口 (v1 用 module.exports
//       导致主屏幕小组件渲染空白)
// ============================================================

const DATA_URL = "https://goodbai37.github.io/probiotic-hotspot/data.json";
const MAX_ITEMS = { small: 3, medium: 5, large: 8 };

// 配色 (深色模式自动适配)
const GREEN = Color.dynamic(new Color("#1f9d61"), new Color("#34d399"));
const BLUE = new Color("#2563eb");
const AMBER = new Color("#d97706");
const INK = Color.dynamic(new Color("#1a2b22"), new Color("#e5e7eb"));
const MUTED = Color.dynamic(new Color("#6b7a70"), new Color("#9ca3af"));
const CARD = Color.dynamic(new Color("#ffffff"), new Color("#1f2937"));

async function fetchLatest() {
  const req = new Request(DATA_URL);
  req.timeoutInterval = 15;
  const records = await req.loadJSON();
  if (!records || records.length === 0) throw new Error("data.json 为空");
  return records[records.length - 1]; // 最后一条 = 最新一天
}

function addItemRow(widget, item, showMeta) {
  const row = widget.addStack();
  row.layoutHorizontally();
  row.centerAlignContent();
  row.spacing = 6;
  row.url = item.url; // 点击整行打开原文

  // 分类圆点: 相关文献=蓝, 法规动态=琥珀
  const dot = row.addStack();
  dot.size = new Size(8, 8);
  dot.cornerRadius = 4;
  dot.backgroundColor = item.tag === "法规动态" ? AMBER : BLUE;

  // 文本列
  const col = row.addStack();
  col.layoutVertically();
  col.spacing = 2;
  col.addSpacer(2);

  const title = col.addText(item.text || "");
  title.font = Font.mediumSystemFont(13);
  title.textColor = INK;
  title.lineLimit = 2;

  if (showMeta) {
    const meta = col.addText(
      [item.journal, item.date].filter(Boolean).join(" · ")
    );
    meta.font = Font.systemFont(10);
    meta.textColor = MUTED;
    meta.lineLimit = 1;
  }

  // 分数徽标
  const score = row.addText(String(item.score ?? ""));
  score.font = Font.boldSystemFont(11);
  score.textColor = GREEN;
}

async function createWidget() {
  const widget = new ListWidget();
  widget.backgroundColor = CARD;
  widget.setPadding(14, 14, 12, 14);

  const family = config.widgetFamily || "medium";
  const limit = MAX_ITEMS[family] || 5;
  const showMeta = family !== "small";

  // 标题行
  const head = widget.addStack();
  head.layoutHorizontally();
  head.centerAlignContent();
  head.spacing = 6;
  const title = head.addText("🦠 益生菌热点");
  title.font = Font.boldSystemFont(16);
  title.textColor = INK;
  head.addSpacer();
  const date = head.addText("加载中…");
  date.font = Font.semiboldSystemFont(11);
  date.textColor = MUTED;
  widget.addSpacer(10);

  try {
    const latest = await fetchLatest();
    date.text = latest.date || "";

    const items = (latest.items || []).slice(0, limit);
    if (!items.length) {
      const empty = widget.addText("今日暂无数据");
      empty.textColor = MUTED;
      empty.font = Font.systemFont(13);
    } else {
      for (const it of items) {
        addItemRow(widget, it, showMeta);
        widget.addSpacer(6);
      }
    }

    // 底部: 分类说明
    widget.addSpacer(4);
    const foot = widget.addStack();
    foot.layoutHorizontally();
    const tip = foot.addText("蓝点=文献 · 琥珀点=法规 · 点击直达原文");
    tip.font = Font.systemFont(9);
    tip.textColor = MUTED;
    tip.lineLimit = 1;
  } catch (e) {
    date.text = "";
    widget.addSpacer(4);
    const err = widget.addText("⚠️ " + (e.message || "加载失败"));
    err.font = Font.mediumSystemFont(13);
    err.textColor = new Color("#dc2626");
    widget.addSpacer(2);
    const retry = widget.addText("请检查网络后长按小组件→编辑→再点完成刷新");
    retry.font = Font.systemFont(9);
    retry.textColor = MUTED;
    retry.lineLimit = 2;
  }

  // 每日 00:30 自动刷新 (iOS 调度, 尽力而为)
  const next = new Date();
  next.setHours(0, 30, 0, 0);
  if (next <= new Date()) next.setDate(next.getDate() + 1);
  widget.refreshAfterDate = next;

  return widget;
}

// ---- 标准入口: 主屏幕小组件必须用 Script.setWidget ----
let widget = await createWidget();
if (config.runsInWidget) {
  Script.setWidget(widget);
  Script.complete();
} else {
  widget.presentMedium();
}
