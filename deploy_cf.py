#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
部署 widget.html 到 Cloudflare Pages（Direct Upload API）
=========================================================
用途: 让手机通过公网 URL 访问小组件，不依赖电脑在线。

前置条件（一次性）:
  1. 注册 Cloudflare 账号: https://dash.cloudflare.com/sign-up
  2. 创建 API Token: My Profile -> API Tokens -> Create Token
     模板选 "Edit Cloudflare Workers" 或自定义，权限需包含:
       Account - Cloudflare Pages - Edit
     （简化: 用模板 "Edit Cloudflare Workers" 通常自带 Pages 编辑权限）
  3. 获取 Account ID: 控制台首页右侧 "Account ID"
  4. 写入凭证文件 .cf_credentials.json:
       {"token": "<API_TOKEN>", "account_id": "<ACCOUNT_ID>"}
     或设置环境变量 CF_API_TOKEN / CF_ACCOUNT_ID

用法:
  python3 deploy_cf.py                 # 部署 widget.html
  python3 deploy_cf.py --project xxx   # 指定项目名（默认 probiotic-hotspot）
部署成功后手机访问: https://<project>.pages.dev/widget.html
"""

import argparse
import json
import logging
import sys
import urllib.request
from pathlib import Path

log = logging.getLogger("deploy_cf")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
WIDGET = BASE_DIR / "widget.html"
ARCHIVE = BASE_DIR / "archive.html"
CRED_FILE = BASE_DIR / ".cf_credentials.json"
DEFAULT_PROJECT = "probiotic-hotspot"

API = "https://api.cloudflare.com/client/v4"


def load_creds() -> tuple[str, str]:
    if CRED_FILE.exists():
        try:
            c = json.loads(CRED_FILE.read_text(encoding="utf-8"))
            return c.get("token", ""), c.get("account_id", "")
        except Exception:
            pass
    return "", ""


def api_call(method: str, path: str, token: str, body: bytes | None = None,
             content_type: str = "application/json", timeout: int = 90) -> dict:
    """调用 Cloudflare API v4，返回 JSON。"""
    req = urllib.request.Request(API + path, method=method, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="部署小组件到 Cloudflare Pages")
    ap.add_argument("--project", default=DEFAULT_PROJECT, help="Pages 项目名")
    args = ap.parse_args()

    token, account_id = load_creds()
    if not token or not account_id:
        log.error("缺少凭证: 请创建 %s 或设置 CF_API_TOKEN/CF_ACCOUNT_ID", CRED_FILE)
        log.error("步骤: 注册 Cloudflare -> 建 API Token(Pages Edit) -> 填 Account ID")
        return 2
    if not WIDGET.exists():
        log.error("缺少 %s，先运行 update_hotspot.py", WIDGET)
        return 2

    # 部署文件清单（存在才上传）
    files = {"widget.html": WIDGET}
    if ARCHIVE.exists():
        files["archive.html"] = ARCHIVE

    # 1) 确保项目存在（404 则创建）
    try:
        api_call("GET", f"/accounts/{account_id}/pages/projects/{args.project}", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            log.info("创建 Pages 项目 %s ...", args.project)
            # Pages 项目创建必须指定生产分支
            body = json.dumps({"name": args.project, "production_branch": "main"}).encode()
            api_call("POST", f"/accounts/{account_id}/pages/projects", token, body)
        else:
            raise

    # 2) Direct Upload 部署（multipart: manifest + 各文件本体）
    #    manifest = 文件名 -> sha256 十六进制摘要
    import hashlib
    manifests, parts = {}, []
    boundary = "----probiotichotspot" + "x" * 20
    for name, path in files.items():
        content = path.read_bytes()
        manifests[name] = hashlib.sha256(content).hexdigest()
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{name}"\r\n'.encode())
        parts.append(b"Content-Type: text/html; charset=utf-8\r\n\r\n")
        parts.append(content)
        parts.append(b"\r\n")
    manifest_json = json.dumps(manifests).encode()
    head = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="manifest"\r\n\r\n',
        manifest_json,
        b"\r\n",
    ]
    body = b"".join(head + parts + [f"--{boundary}--\r\n".encode()])
    log.info("上传 %s -> %s ...", ", ".join(files), args.project)
    doc = api_call(
        "POST",
        f"/accounts/{account_id}/pages/projects/{args.project}/deployments",
        token, body,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=120,
    )
    if not doc.get("success"):
        log.error("部署失败: %s", doc.get("errors"))
        return 1
    dep = doc.get("result", {})
    log.info("✅ 部署成功! 部署ID=%s", dep.get("id"))
    log.info("手机访问: https://%s.pages.dev/widget.html", args.project)
    log.info("          https://%s.pages.dev/archive.html", args.project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
