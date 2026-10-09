"""試跑：python -m src.core → 列出目前 15 國各有幾台 VPN Gate 伺服器。"""

import sys

from .vpngate import availability, fetch_list, filter_targets, group_by_country, parse_list


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # 避免 Windows 主控台中文亂碼
    servers = parse_list(fetch_list())
    print(f"VPN Gate 本次回傳 {len(servers)} 台伺服器\n")
    groups = group_by_country(filter_targets(servers))
    for code, name, count in availability(servers):
        mark = "✅" if count else "❌"
        best = f"  最佳：{groups[code][0].sstp_host}（分數 {groups[code][0].score}）" if count else ""
        print(f"{mark} {code} {name}：{count} 台{best}")


if __name__ == "__main__":
    main()
