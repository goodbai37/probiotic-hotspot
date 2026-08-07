# 复现 Prompt：益生菌研发热点速览（probiotic-hotspot）

> 用法：把下面方框里的内容完整复制，交给另一个 AI 助手或工程师，即可从零复现整个项目。

---

```
# 任务：从零复现「益生菌研发热点速览」项目

你是一个 AI 软件工程师。请根据以下规格，完整复现一个益生菌研发热点速览系统。
所有代码用英文编写，与用户的交流用中文。

## 一、项目定位

一个「益生菌研发热点速览」信息管道 + 前端展示系统：

1. **数据管道**：每天自动抓取益生菌领域的最新文献和法规动态，用本地 LLM 提炼成中文热点条目
2. **评分排序**：对每条热点打分（相关性 + 新鲜度 + 菌株特异性），每日取 Top 10
3. **前端展示**：手机可访问的滑动浏览页（每页一条卡片，左右滑动翻页）+ 列表页 + 历史存档页
4. **安装方案**：
   - 普通用户/安卓：PWA「添加到主屏幕」（零安装）
   - iOS 进阶用户：Scriptable 小组件（主屏幕真小组件，点击跳转滑动页）
5. **部署**：GitHub Pages 静态托管，每日自动更新

## 二、环境与依赖

- Python 3.10+（标准库为主：urllib/json/re，避免重依赖）
- 本地 Ollama（http://127.0.0.1:11434），模型 qwen3:8b（GPU 加速，think:false 模式）
- GitHub CLI（gh）用于部署推送
- 部署目标：GitHub Pages（静态页 + data.json）

## 三、数据管道（update_hotspot.py）

### 3.1 数据源（3 个）

1. **PubMed E-utilities**（文献源）：
   - esearch 查询最近 7 天益生菌相关文献（检索式含 probiotics/probiotic + 益生菌，AND 各疾病/功能方向词）
   - 按日期排序，取前 ~30 篇 PMID
   - efetch 拉每篇摘要（截断 3000 字符），供 LLM 提炼
   - 注意：摘要截断太短（<300字符）会让 LLM 丢掉结论、靠背景猜功效导致编造，必须 ≥600 字符
2. **食品伙伴网 foodmate.net**（法规/行业动态）：
   - 抓 https://news.foodmate.net 益生菌标签页列表
   - 每条抓详情页解析**真实发布日期**（页面有「时间：YYYY-MM-DD」格式；注意同页还有中文日期「YYYY年M月D日」，正则要先 ISO 后中文，否则会被正文里的法规日期干扰）
   - 抓详情页正文（正文在 `<div class="content" id="article">` 容器内，**嵌套 div，不能用非贪婪 `</div>` 截断**，以「下一篇」为正文结束标志），供 LLM 生成概括
3. **卫健委 NHC**（可选）：公示查询，反爬严格（412），失败自动跳过不阻塞

### 3.2 LLM 提炼（Ollama qwen3:8b）

- **llm_refine**：每条文献 → 中文短句标题（格式必须「XX菌可XXX」或「XX可XXX」），用 smart_abst() 首尾拼接摘要（头400+尾600字符）注入 prompt 防编造
- **防编造规则**：酶工程/食品加工类研究标 0 剔除；结论必须来自摘要；强制中文输出
- **llm_brief**：每条（文献+法规）→ ≤60 字中文内容概括
  - 文献用摘要、法规用抓到的正文、卫健委用标题
  - 输出格式「行号|概括」，temperature 0.2
  - ⚠️ 解析坑：LLM 可能把 prompt 示例「行号」字面抄进输出（如 `1|行号|1|概括`），解析必须**取最后一个 `|` 之后的内容**并剔除「行号」字面量，不能只用正则 group(2)
- **BATCH=5** 分批（防止 prompt 过长输出漂移全标 0）
- **Ollama 调用**：POST /api/chat，`think:false`，`options.temperature:0.2`

### 3.3 评分排序（scoring.py）

- 每条算 score：相关性(与益生菌方向的匹配) + 新鲜度(日期衰减) + 特异性(含菌株名加分，权重 0.20)
- 菌株名检测：正则匹配常见菌属（Bifidobacterium/Lactobacillus/Lacticaseibacillus/Limosilactobacillus/Lactiplantibacillus/Escherichia/Faecalibacterium/Enterococcus/双歧杆菌/乳杆菌/乳杆菌等），**不能用 \b 单词边界（中文环境失效）**
- 按 score 降序取 Top 10
- 分组：相关文献 / 法规动态 两组，组内按分数降序

### 3.4 输出（data.json）

```json
[
  {
    "date": "2026-08-07",
    "items": [
      {
        "text": "婴儿双歧杆菌CCFM1445促进骨生长",   // 中文短句标题
        "tag": "相关文献",                            // 或「法规动态」
        "score": 73,
        "url": "https://pubmed.ncbi.nlm.nih.gov/xxx/",
        "journal": "Probiotics and Antimicrobial Proteins",
        "date": "2026-08-03",
        "brief": "研究显示 B. longum subsp. infantis 促进小鼠骨骼生长和骨量增加"  // ≤60字中文概括
      }
    ]
  }
]
```

- 按日期升序（最新在最后）
- 同一天只保留最新一次运行结果

## 四、前端页面

### 4.1 slides.html（核心：滑动浏览页）

- 全屏卡片，左右滑动翻页，每页一条热点
- 卡片内容：标签（🔬相关文献蓝 / ⚖️法规动态琥珀）→ 标题（28px 粗体）→ 💡 中文概括（绿左边框毛玻璃卡片，max 5 行截断）→ 期刊·日期 → 热度徽章 → 「查看原文」渐变按钮 → 页码「3/10 · 左右滑动」
- **⚠️ 关键技术点（踩坑总结）**：
  1. 所有定位用**像素基准** `W = window.innerWidth`（卡片 `left:i*W`、deck `width:N*W`、卡片 `width:W`、翻页 `translateX(-cur*W)`），**不要用百分比**——iOS Safari 对 `fixed+transform 百分比` 渲染有 bug 导致翻页空白
  2. **deck 容器宽度必须 = N×W**（容纳所有卡片），否则 `overflow:hidden` 会把第 2 张以后的卡片全部裁掉
  3. 卡片宽度必须固定 W px（deck 变宽后卡片不能 width:100% 跟随变 N 倍，否则超屏）
  4. 触摸翻页用原生 touchstart/touchmove/touchend 监听：横向位移 >15% 屏宽翻页，纵向不拦截，位移不足回弹
  5. resize 时重算所有卡片 left/width 和 deck 宽度
- PWA 标签：manifest-slides.json、apple-touch-icon、mobile-web-app-capable
- 数据：`fetch(data.json, {cache:"no-store"})`（避免缓存旧数据）
- 深色模式适配（prefers-color-scheme）

### 4.2 widget.html（列表页）

- 竖排列表，每条显示标签/标题/分数/箭头，点击直达原文
- 从 data.json 动态渲染

### 4.3 archive.html（历史存档）

- 按日期倒序展示所有历史热点

### 4.4 index.html（总入口页）

- 4 个入口卡片：滑动浏览 / 列表查看 / 历史存档 / 装到桌面
- 自动读 data.json 显示「数据更新至 日期 · N 条」

### 4.5 install-widget.html（安装引导页）

- 顶部绿色「零安装方案」区块：iPhone Safari 分享→添加到主屏幕 / 安卓 Chrome 菜单⋮→安装应用
- 下方 iOS 进阶方案：Scriptable 小组件说明 + 一键导入链接
- ⚠️ 一键导入 URL scheme 必须带 `scriptName` 参数，否则 Scriptable 导入空白：
  `scriptable:///add?scriptName=probiotic-hotspot&url=...`

### 4.6 PWA 支持

- manifest.json（widget 版）、manifest-slides.json（滑动版）
- sw.js：缓存静态资源（widget/archive/slides/manifest/icon），版本号升级时换 CACHE_NAME
- icon-192.png / icon-512.png / icon.svg
- 注意：**manifest/icon/sw 必须纳入 git 跟踪**，否则线上 404、PWA 无法安装

## 五、Scriptable 小组件（probiotic-widget.js）

**⚠️ 最重要的架构决策：不要用 WebView！**

- 用户 Scriptable 版本旧（无 Page API、WebView 兼容性差）
- 最可靠方案：**不依赖 WebView，顶层直接执行**
- 代码结构：
  ```js
  // 变量: SLIDES_URL = 线上 slides.html 地址
  async function main() {
    const config = (args && args.widgetParameter) ? JSON.parse(args.widgetParameter) : {};
    if (config.runsInWidget) {
      // 小组件模式: 显示标题+前2条热点+"滑动查看"
      // 点击 -> Safari.open(SLIDES_URL)
    } else {
      // 点▶运行 -> 直接 Safari.open(SLIDES_URL)
    }
  }
  await main();  // 兼容旧版 Scriptable, 不用顶层 await 以外的语法
  ```
- **不用 `module.exports`**（不执行）；**必须 `Script.setWidget(widget)`** 顶层直接调用
- 小组件显示：标题「🦠 益生菌热点」+ 今日 Top 2 条目 + 底部提示
- 点击行为：`Safari.open(SLIDES_URL)`

## 六、部署

### 6.1 GitHub Pages

- 仓库结构：根目录直接部署（文件都在根）
- 每日推送：deploy_git.sh（git add 清单文件 → commit → push，无变化跳过）
- ⚠️ 部署清单必须包含：widget.html slides.html archive.html index.html probiotic-hotspot-mobile.html data.json probiotic-widget.js
- ⚠️ 踩坑：git push 直连可能超时或远程分叉失败；可靠路径是 **gh api PUT 逐文件推送**（先 GET 最新 sha，带 sha PUT，409 说明并发过期需重取重试）
- 每次 push 后 GitHub Pages 构建需 ~40-60 秒

### 6.2 定时任务

- cron 每天 08:30 (Asia/Shanghai) 运行：
  1. `python3 update_hotspot.py`（抓数据+LLM 提炼+生成 data.json 和所有页面）
  2. `./deploy_git.sh`（推送 GitHub）
- 运行结果汇报给用户

## 七、质量标准

1. **防幻觉**：LLM 提炼必须基于摘要/正文，禁止编造；酶工程/食品加工类标 0 剔除；后置过滤剔除英文短句
2. **菌株名准确**：LLM 偶尔把「植物乳杆菌」写成「乳酸植物杆菌」，可接受但尽量纠
3. **URL/标题必须与 data.json 一一对应**，不能有孤儿条目
4. **法规动态真实发布日期**：从详情页解析，不能用当天日期
5. **中文概括**：所有条目（文献+法规）都要 ≤60 字中文概括，法规无摘要时从正文概括
6. **代码规范**：Python 用 pathlib/函数化/logging；前端无重依赖、深色模式适配、safe-area 适配

## 八、验收清单

- [ ] 跑 update_hotspot.py 能生成含中文概括的 data.json（文献+法规都有 brief）
- [ ] slides.html 手机 Safari 打开能左右滑动翻页，无空白页、无超屏
- [ ] 深色模式正常
- [ ] PWA 可添加到主屏幕（manifest/icon/sw 均 200）
- [ ] Scriptable 导入脚本后 ▶ 运行直接跳转滑动页
- [ ] GitHub Pages 部署后所有页面 200，data.json 可 fetch
- [ ] 每日 cron 自动运行并部署
