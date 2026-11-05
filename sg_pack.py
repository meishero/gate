#!/usr/bin/env python3
"""
把「你自己的优选IP」和「检测结果里最快的 SSTP 节点」拼成 edgetunnel 能吃的 nodes.txt。

规则:
    1. 优先取 SG（新加坡）最快的 1 个节点；
    2. 没有 SG 就取 JP（日本）最快的 1 个；
    3. 两个都没有 -> 只输出入口IP，不拼 $sstp。

输出格式:
    [2606:4700:...]:443#新加坡-住宅-01$sstp://vpn:vpn@vpnxxxx.opengw.net:1780

用法(在 vpngate.py 之后跑，依赖 public/data.json):
    python sg_pack.py

环境变量:
    HOSTS_URL          你的优选IP列表(每行  [v6]:443#备注  或  1.2.3.4:443)
    HOSTS_FILE         本地文件路径，存在时优先于 HOSTS_URL (默认 ./hosts.txt)
    PREFER_COUNTRIES   出口地区优先顺序 (默认 SG,JP)
    TOP_N              每个地区取几个最快节点 (默认 1)
    MAX_HOSTS          最多用多少个入口IP (默认 20)
"""
import json
import os
import sys

import requests

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.environ.get("PUBLIC_DIR", os.path.join(REPO_DIR, "public"))
DATA_PATH = os.path.join(PUBLIC_DIR, "data.json")
OUT_PATH = os.path.join(PUBLIC_DIR, "nodes.txt")

HOSTS_URL = os.environ.get(
    "HOSTS_URL",
    "https://raw.githubusercontent.com/meishero/cf-bestip/main/best_ip_v6_yidong.txt",
)
HOSTS_FILE = os.environ.get("HOSTS_FILE", os.path.join(REPO_DIR, "hosts.txt"))
PREFER = [
    c.strip().upper()
    for c in os.environ.get("PREFER_COUNTRIES", "SG,JP").split(",")
    if c.strip()
]
TOP_N = max(1, int(os.environ.get("TOP_N", "1")))
MAX_HOSTS = max(1, int(os.environ.get("MAX_HOSTS", "20")))

COUNTRY_ZH = {
    "SG": "新加坡", "JP": "日本", "MY": "马来西亚", "TH": "泰国", "VN": "越南",
    "KR": "韩国", "HK": "香港", "TW": "台湾", "US": "美国", "CA": "加拿大",
    "RU": "俄罗斯", "DE": "德国", "GB": "英国", "FR": "法国", "NL": "荷兰",
    "AU": "澳大利亚", "IN": "印度", "ID": "印度尼西亚", "PH": "菲律宾",
}


def log(msg):
    print(msg, flush=True)


def load_hosts():
    text = None
    if HOSTS_FILE and os.path.exists(HOSTS_FILE):
        log(f"[hosts] 读取本地文件 {HOSTS_FILE}")
        with open(HOSTS_FILE, "r", encoding="utf-8") as f:
            text = f.read()
    if text is None:
        log(f"[hosts] 拉取 {HOSTS_URL}")
        try:
            resp = requests.get(HOSTS_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0 (gate-pack)"})
            resp.raise_for_status()
            text = resp.text
        except Exception as exc:
            log(f"[hosts] 拉取失败: {type(exc).__name__}: {exc}")
            return []

    hosts = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = line.split("#")[0].strip()
        if not entry:
            continue
        # 没有端口就补 443；IPv6 必须带方括号
        tail = entry.rsplit("]", 1)[-1] if "]" in entry else entry
        if ":" not in tail:
            entry = f"{entry}:443"
        hosts.append(entry)
        if len(hosts) >= MAX_HOSTS:
            break
    return hosts


def pick_nodes(available):
    def latency(n):
        v = n.get("latency_ms")
        return (v is None, v if isinstance(v, (int, float)) else 1e9)

    def only(code):
        return sorted(
            [n for n in available if str(n.get("country_code") or "").upper() == code],
            key=latency,
        )

    for code in PREFER:
        nodes = only(code)
        if nodes:
            return nodes[:TOP_N], code
    return [], None


def main():
    if not os.path.exists(DATA_PATH):
        sys.exit(f"找不到 {DATA_PATH}，请先成功运行 vpngate.py")
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    available = data.get("available") or []
    if not available:
        sys.exit("data.json 里没有可用节点：检测 Worker 那步可能全挂了")

    hosts = load_hosts()
    if not hosts:
        log("[hosts] 没拿到优选IP，保留 vpngate.py 生成的原始 nodes.txt（本次不重写）")
        return

    picked, country = pick_nodes(available)

    if not picked:
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(hosts) + "\n")
        log(f"[out] 没有 {'/'.join(PREFER)} 节点，只输出 {len(hosts)} 个入口（不带 $sstp）")
        return

    zh = COUNTRY_ZH.get(country, country)
    lines = []
    for n in picked:
        kind = "住宅" if n.get("residential") == "residential" else "机房"
        link = n.get("link") or f"sstp://vpn:vpn@{n['host']}:{n['port']}"
        log(f"[pick] {country} {n.get('host')}:{n.get('port')} 延迟={n.get('latency_ms')}ms -> {link}")
        for h in hosts:
            lines.append(f"{h}#{zh}-{kind}-{len(lines) + 1:02d}${link}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    log(f"[out] 写入 {len(lines)} 行 -> {OUT_PATH}")
    log(f"[out] 入口 {len(hosts)} 个 × 出口 {len(picked)} 个")


if __name__ == "__main__":
    main()
