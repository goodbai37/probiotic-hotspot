// 益生菌热点速览 · 主屏幕小组件 (Scriptable)
// ============================================================
// 数据源: https://goodbai37.github.io/probiotic-hotspot/data.json
// 用法:
//   1. App Store 安装免费的 "Scriptable"
//   2. 用 Safari 打开本脚本的 raw 链接, 选择"用 Scriptable 打开"导入;
//      或打开 Scriptable → 右上角 + 新建脚本 → 粘贴本代码
//   3. 长按主屏幕 → 左上角 + → 搜索 Scriptable → 添加小组件(小/中/大)
//   4. 长按刚添加的小组件 → 编辑小组件 → 脚本选 "probiotic-widget" → 完成
//   5. 可与其它小组件叠放, 或拖入"智能叠放"自动轮换
// 尺寸: 小=3条 / 中=5条 / 大=8条, 点击条目直达原文
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
  req.timeoutInterval = 10;
  const records = await req.loadJSON();
  if (!records || !records.length) throw new Error("no data");
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

async function run() {
  const widget = new ListWidget();
  widget.backgroundColor = CARD;
  widget.setPadding(14, 14, 12, 14);

  const family = config.widgetFamily || "medium";
  const limit = MAX_ITEMS[family] || 5;
  const showMeta = family !== "small";

  try {
    const latest = await fetchLatest();
    const items = (latest.items || []).slice(0, limit);

    // 标题行
    const head = widget.addStack();
    head.layoutHorizontally();
    head.centerAlignContent();
    head.spacing = 6;
    const title = head.addText("🦠 益生菌热点");
    title.font = Font.boldSystemFont(16);
    title.textColor = INK;
    head.addSpacer();
    const date = head.addText(latest.date || "");
    date.font = Font.semiboldSystemFont(11);
    date.textColor = MUTED;
    widget.addSpacer(10);

    if (!items.length) {
      widget.addText("今日暂无数据").textColor = MUTED;
    } else {
      for (const it of items) {
        addItemRow(widget, it, showMeta);
        widget.addSpacer(6);
      }
    }

    // 底部: 更新提示 + 分类说明
    widget.addSpacer(4);
    const foot = widget.addStack();
    foot.layoutHorizontally();
    const tip = foot.addText("相关文献 · 法规动态 · 点击直达原文");
    tip.font = Font.systemFont(9);
    tip.textColor = MUTED;
    tip.lineLimit = 1;
  } catch (e) {
    widget.addText("⚠️ 数据加载失败");
    widget.addText("请打开 Scriptable 检查网络后重试").textColor = MUTED;
  }

  // 每日 00:30 自动刷新 (Scriptable 受 iOS 调度限制, 尽力而为)
  const next = new Date();
  next.setHours(0, 30, 0, 0);
  if (next <= new Date()) next.setDate(next.getDate() + 1);
  widget.refreshAfterDate = next;

  return widget;
}

module.exports = { run };
