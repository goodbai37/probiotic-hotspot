# 益生菌研发热点速览 (Probiotic Hotspot)

AI 驱动的益生菌领域情报系统：**每日自动抓取最新文献与法规动态 → LLM 提炼中文热点 → 评分排序 → 手机滑动浏览**。

在线体验：https://goodbai37.github.io/probiotic-hotspot/

---

## 功能特性

- 🔬 **每日自动更新**：PubMed（文献）+ 食品伙伴网（法规/行业动态）+ 卫健委（公示）
- 🤖 **本地 LLM 提炼**（Ollama qwen3:8b）：中文短句标题（「XX菌可XXX」）+ ≤60 字内容概括，防编造质控
- 📊 **热度评分**：相关性 + 新鲜度 + 菌株特异性，每日 Top 10，分「相关文献 / 法规动态」两组
- 📱 **多端展示**：全屏滑动浏览页（每页一条卡片）+ 列表页 + 历史存档 + 总入口页
- 📲 **零门槛安装**：PWA 添加到主屏幕（普通用户/安卓）；iOS 可用 Scriptable 真小组件
- 🌙 深色模式、毛玻璃卡片、safe-area 适配

## 项目结构

```
probiotic-hotspot/
├── update_hotspot.py           # 主数据管道（抓取 + LLM 提炼 + 评分 + 输出 data.json）
├── scoring.py                  # 评分模块（相关性/新鲜度/菌株特异性）
├── backfill_abstract.py        # 历史数据摘要回填脚本
├── backfill_brief.py           # 历史数据中文概括回填脚本
├── deploy_git.sh               # GitHub Pages 每日部署脚本
├── deploy_cf.py                # Cloudflare Pages 备用部署
├── slides.html                 # ★ 核心页面：全屏滑动浏览（每页一条热点卡片）
├── widget.html                 # 列表页（今日 Top 10）
├── archive.html                # 历史存档
├── index.html                  # 总入口页
├── install-widget.html         # 安装引导（PWA 零门槛 + Scriptable 小组件）
├── probiotic-hotspot-mobile.html  # 可嵌入的信息流组件（供其它网站 iframe 使用，每日自动生成）
├── probiotic-widget.js         # Scriptable iOS 小组件脚本
├── manifest*.json / sw.js / icon*  # PWA 支持
└── data.json                   # 每日数据输出（含中文概括 brief）
```

## 快速开始

### 1. 数据管道

```bash
# 依赖: Python 3.10+ (标准库), 本地 Ollama (qwen3:8b, think:false)
python3 update_hotspot.py        # 抓取+提炼+生成 data.json
python3 update_hotspot.py --no-llm  # 跳过 LLM（降级模式）
```

### 2. 本地预览

```bash
python3 -m http.server 8080
# 手机/浏览器访问 http://<IP>:8080/slides.html
```

### 3. 部署 GitHub Pages

```bash
./deploy_git.sh                  # 推送核心文件到 main 分支
```

### 4. 定时任务（可选）

```bash
# cron 每天 08:30 自动更新 + 部署
# 30 8 * * * cd /path/to/probiotic-hotspot && python3 update_hotspot.py && ./deploy_git.sh
```

## 完整复现指南

👉 见 [`REPRODUCE_PROMPT.md`](./REPRODUCE_PROMPT.md) —— 包含全部技术细节与踩坑记录，
可直接作为 Prompt 交给任何 AI 助手从零复现本项目。

## 技术要点（踩坑总结）

- **滑动页定位用像素基准**（`W=innerWidth`），不用百分比——iOS Safari 对 `fixed+transform 百分比` 渲染有 bug
- **deck 容器宽度必须 = 卡片数 × 屏宽**，否则 `overflow:hidden` 裁掉后面的卡片
- **LLM 概括解析**：输出可能带「行号」字面量前缀（`1|行号|1|概括`），取最后一个 `|` 之后的内容
- **Scriptable 小组件不用 WebView**（旧版本兼容性差），直接 `Safari.open` 跳转网页
- **部署用 gh api PUT 逐文件推**（git push 直连不稳），409 时重取 sha 重试

## 数据说明

- `data.json` 为示例数据（每日自动更新），含 `brief` 中文概括字段
- 所有 LLM 提炼均基于摘要/正文，禁止编造；酶工程/食品加工类自动剔除
