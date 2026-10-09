"""查目前對外 IP 與國家（Cloudflare 公開的 trace 頁面，HTTPS、免註冊）。"""

import urllib.request

TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"


def public_location(timeout: float = 15) -> dict[str, str]:
    req = urllib.request.Request(TRACE_URL, headers={"User-Agent": "AIXAI-VPN/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    fields = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return {"ip": fields.get("ip", ""), "loc": fields.get("loc", "")}
