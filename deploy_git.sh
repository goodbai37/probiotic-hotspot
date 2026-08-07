#!/usr/bin/env bash
# 部署到 GitHub Pages: 推送 widget.html + archive.html + index.html + 移动组件
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

# GitHub 直连网络慢，放宽 git 超时容忍
git config --global http.lowSpeedLimit 1
git config --global http.lowSpeedTime 300

# 有变化才推送（避免每天产生空 commit）
if ! git diff --quiet -- widget.html archive.html index.html probiotic-hotspot-mobile.html; then
    git add widget.html archive.html index.html probiotic-hotspot-mobile.html
    git commit -m "每日更新 $(date +%F) $(date +%H:%M)" || true
    # push 重试最多 3 次（网络不稳）
    for i in 1 2 3; do
        if git push -q origin main; then
            echo "✅ GitHub Pages 已更新"
            exit 0
        fi
        echo "⚠️ push 失败(第${i}次)，5秒后重试..."
        sleep 5
    done
    echo "❌ push 连续失败，请检查网络"
    exit 1
else
    echo "无变化，跳过推送"
fi
