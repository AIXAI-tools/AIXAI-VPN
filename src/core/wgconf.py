"""WireGuard 設定檔（VPNBook）解析與檢查（ADR-011、TASK-009）。

安全原則：
- 錯誤訊息與摘要一律不包含私鑰
- 只接受 Endpoint 為 *.vpnbook.com 的設定
- 拒絕任何會執行指令的欄位（PreUp/PostUp 等）
- 強制 AllowedIPs 涵蓋 0.0.0.0/0 與 ::/0 → 全部流量走 VPN，且啟用 WireGuard 內建 kill switch
"""

import base64
import ipaddress
import re
from dataclasses import dataclass

ALLOWED_KEYS = {
    "interface": {"privatekey", "address", "dns", "mtu", "listenport"},
    "peer": {"publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive"},
}
# VPNBook 主機名稱前綴 → 國家代碼（vpnbook.com/freevpn 列出的 WireGuard 伺服器）
HOST_COUNTRY = {"us": "US", "ca": "CA", "uk": "GB", "de": "DE", "fr": "FR", "pl": "PL"}
HOST_RE = re.compile(r"^([a-z]{2})\d+\.vpnbook\.com$")
# vpnbook.com/freevpn/wireguard-vpn 列出的 WireGuard 伺服器（2026-10-09）。
# 實際下載的設定檔 Endpoint 是 IP → 用這份清單解析出的 IP 比對，確認真的是 VPNBook 的伺服器。
KNOWN_HOSTS = ["us16", "us178", "ca149", "ca196", "uk205", "uk68", "de20", "de220", "fr200", "fr2311"]
MAX_SIZE = 4096


class ConfigError(ValueError):
    pass


@dataclass
class WgConfig:
    interface: dict[str, str]
    peer: dict[str, str]

    @property
    def endpoint_host(self) -> str:
        return self.peer["endpoint"].rsplit(":", 1)[0].strip("[]").lower()

    @property
    def country(self) -> str:
        m = HOST_RE.match(self.server)
        return HOST_COUNTRY.get(m.group(1), "") if m else ""

    @property
    def server(self) -> str:
        """VPNBook 主機名稱（Endpoint 是 IP 時，為比對後的名稱）。"""
        return getattr(self, "_server", "") or self.endpoint_host

    def summary(self) -> dict:
        """給介面顯示用；不含任何金鑰。"""
        return {"server": self.server, "country": self.country}

    def render(self) -> str:
        names = {"privatekey": "PrivateKey", "address": "Address", "dns": "DNS", "mtu": "MTU",
                 "listenport": "ListenPort", "publickey": "PublicKey", "presharedkey": "PresharedKey",
                 "allowedips": "AllowedIPs", "endpoint": "Endpoint", "persistentkeepalive": "PersistentKeepalive"}
        lines = ["[Interface]"] + [f"{names[k]} = {v}" for k, v in self.interface.items()]
        lines += ["", "[Peer]"] + [f"{names[k]} = {v}" for k, v in self.peer.items()]
        return "\n".join(lines) + "\n"


def _is_key(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except ValueError:
        return False


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def parse(text: str, resolve_known=None) -> WgConfig:
    """resolve_known：回傳 {IP: 主機名稱} 的函式，用來確認 IP 形式的 Endpoint 是 VPNBook 的伺服器。"""
    if len(text) > MAX_SIZE:
        raise ConfigError("設定檔太大，不像 WireGuard 設定檔")
    sections: list[tuple[str, dict]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip().lower()
            if name not in ALLOWED_KEYS:
                raise ConfigError(f"不認得的區段：[{name}]")
            sections.append((name, {}))
            continue
        if "=" not in line or not sections:
            raise ConfigError("格式錯誤（不是 key = value）")
        key, value = (x.strip() for x in line.split("=", 1))
        key = key.lower()
        name, values = sections[-1]
        if key not in ALLOWED_KEYS[name]:
            raise ConfigError(f"不允許的欄位：{key}")  # 包含 PreUp/PostUp 等會執行指令的欄位
        values[key] = value

    kinds = [n for n, _ in sections]
    if kinds.count("interface") != 1 or kinds.count("peer") != 1:
        raise ConfigError("必須剛好一個 [Interface] 與一個 [Peer]")
    cfg = WgConfig(dict(next(v for n, v in sections if n == "interface")),
                   dict(next(v for n, v in sections if n == "peer")))

    for section, key in (("interface", "privatekey"), ("peer", "publickey")):
        val = getattr(cfg, section).get(key, "")
        if not _is_key(val):
            raise ConfigError(f"{key} 缺少或格式錯誤")  # 不把值本身寫進訊息
    if "presharedkey" in cfg.peer and not _is_key(cfg.peer["presharedkey"]):
        raise ConfigError("presharedkey 格式錯誤")
    if "address" not in cfg.interface:
        raise ConfigError("缺少 Address")
    if "endpoint" not in cfg.peer or not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", cfg.peer["endpoint"]):
        raise ConfigError("Endpoint 缺少或格式錯誤")
    host = cfg.endpoint_host
    if is_ip(host):
        known = resolve_known() if resolve_known else {}
        if host not in known:
            raise ConfigError(f"這個 IP 不是已知的 VPNBook 伺服器（收到 {host}）")
        cfg._server = known[host]
    elif not host.endswith(".vpnbook.com"):
        raise ConfigError(f"只接受 VPNBook 的伺服器（收到 {host}）")

    # 全部流量走 VPN：補齊 0.0.0.0/0 與 ::/0（WireGuard 遇到 /0 會自動啟用內建 kill switch）
    allowed = [x.strip() for x in cfg.peer.get("allowedips", "").split(",") if x.strip()]
    for route in ("0.0.0.0/0", "::/0"):
        if route not in allowed:
            allowed.append(route)
    cfg.peer["allowedips"] = ", ".join(allowed)
    return cfg


def resolve_known_hosts() -> dict[str, str]:
    """把已知的 VPNBook 主機名稱解析成 IP：{IP: 主機名稱}。查不到的略過。"""
    import socket

    result = {}
    for name in KNOWN_HOSTS:
        host = f"{name}.vpnbook.com"
        try:
            for info in socket.getaddrinfo(host, None):
                result[info[4][0]] = host
        except OSError:
            continue
    return result

