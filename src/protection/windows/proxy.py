"""Windows 系統代理（Proxy）設定：Tor 模式時讓瀏覽器改走 Tor（ADR-011、TASK-011 設計 ①②③）。

- 用官方 WinINET API（InternetSetOption + INTERNET_OPTION_PER_CONNECTION_OPTION）設定目前使用者的代理
- 改之前先把原本的設定備份到 %LOCALAPPDATA%\\AIXAI-VPN\\proxy-backup.json（"active": true）
- 還原後把備份標成 "active": false（不刪檔）
- App 當掉時，由看門狗（proxy_watchdog.py）讀備份自動還原
"""

import ctypes
import json
import os
from ctypes import POINTER, Structure, Union, byref, c_uint32, c_void_p, c_wchar_p, sizeof
from pathlib import Path

BACKUP_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "proxy-backup.json"
BYPASS = "localhost;127.*;<local>"  # 本機位址不走代理（App 介面才不會斷）

INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_PER_CONNECTION_OPTION = 75

PER_CONN_FLAGS = 1
PER_CONN_PROXY_SERVER = 2
PER_CONN_PROXY_BYPASS = 3
PER_CONN_AUTOCONFIG_URL = 4

PROXY_TYPE_DIRECT = 0x1
PROXY_TYPE_PROXY = 0x2


class _VALUE(Union):
    _fields_ = [("dwValue", c_uint32), ("pszValue", c_void_p), ("ftValue", ctypes.c_uint64)]


class PER_CONN_OPTION(Structure):
    _fields_ = [("dwOption", c_uint32), ("Value", _VALUE)]


class PER_CONN_OPTION_LIST(Structure):
    _fields_ = [("dwSize", c_uint32), ("pszConnection", c_wchar_p), ("dwOptionCount", c_uint32),
                ("dwOptionError", c_uint32), ("pOptions", POINTER(PER_CONN_OPTION))]


def _wininet():
    lib = ctypes.WinDLL("wininet.dll")
    lib.InternetQueryOptionW.argtypes = [c_void_p, c_uint32, c_void_p, POINTER(c_uint32)]
    lib.InternetSetOptionW.argtypes = [c_void_p, c_uint32, c_void_p, c_uint32]
    return lib


def query() -> dict:
    """讀取目前的代理設定：{"flags", "server", "bypass", "autoconfig"}。"""
    opts = (PER_CONN_OPTION * 4)()
    for i, o in enumerate((PER_CONN_FLAGS, PER_CONN_PROXY_SERVER, PER_CONN_PROXY_BYPASS, PER_CONN_AUTOCONFIG_URL)):
        opts[i].dwOption = o
    lst = PER_CONN_OPTION_LIST(sizeof(PER_CONN_OPTION_LIST), None, 4, 0, opts)
    size = c_uint32(sizeof(lst))
    if not _wininet().InternetQueryOptionW(None, INTERNET_OPTION_PER_CONNECTION_OPTION, byref(lst), byref(size)):
        raise OSError(f"讀取代理設定失敗（{ctypes.GetLastError()}）")

    def text(i):
        p = opts[i].Value.pszValue
        if not p:
            return None
        s = ctypes.wstring_at(p)
        ctypes.windll.kernel32.GlobalFree(c_void_p(p))  # 文件規定由呼叫端釋放
        return s

    return {"flags": opts[0].Value.dwValue, "server": text(1), "bypass": text(2), "autoconfig": text(3)}


def apply(settings: dict) -> None:
    """套用代理設定並通知所有程式重新讀取。"""
    keep = []
    opts = (PER_CONN_OPTION * 4)()
    values = [(PER_CONN_FLAGS, settings["flags"]), (PER_CONN_PROXY_SERVER, settings.get("server")),
              (PER_CONN_PROXY_BYPASS, settings.get("bypass")), (PER_CONN_AUTOCONFIG_URL, settings.get("autoconfig"))]
    for i, (opt, val) in enumerate(values):
        opts[i].dwOption = opt
        if opt == PER_CONN_FLAGS:
            opts[i].Value.dwValue = int(val)
        else:
            buf = ctypes.create_unicode_buffer(val or "")
            keep.append(buf)
            opts[i].Value.pszValue = ctypes.addressof(buf)
    lst = PER_CONN_OPTION_LIST(sizeof(PER_CONN_OPTION_LIST), None, 4, 0, opts)
    lib = _wininet()
    if not lib.InternetSetOptionW(None, INTERNET_OPTION_PER_CONNECTION_OPTION, byref(lst), sizeof(lst)):
        raise OSError(f"設定代理失敗（{ctypes.GetLastError()}）")
    lib.InternetSetOptionW(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0)
    lib.InternetSetOptionW(None, INTERNET_OPTION_REFRESH, None, 0)


def tor_settings(port: int) -> dict:
    # 只開「手動代理」：關掉自動偵測與 PAC，避免它們蓋過我們的設定
    return {"flags": PROXY_TYPE_DIRECT | PROXY_TYPE_PROXY, "server": f"127.0.0.1:{int(port)}",
            "bypass": BYPASS, "autoconfig": ""}


class SystemProxy:
    def __init__(self, backup_path: Path = BACKUP_PATH, query_fn=query, apply_fn=apply) -> None:
        self.backup_path = backup_path
        self._query, self._apply = query_fn, apply_fn

    def _read_backup(self) -> dict | None:
        try:
            return json.loads(self.backup_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_backup(self, data: dict) -> None:
        self.backup_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.backup_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.backup_path)

    def set_tor(self, port: int) -> None:
        backup = self._read_backup()
        if not (backup and backup.get("active")):  # 已經是我們改過的就不要再備份一次（避免把 Tor 設定當成原始值）
            self._write_backup({"active": True, "original": self._query()})
        self._apply(tor_settings(port))

    def restore(self) -> bool:
        """有啟用中的備份才還原。回傳是否有還原。"""
        backup = self._read_backup()
        if not (backup and backup.get("active")):
            return False
        self._apply(backup["original"])
        backup["active"] = False
        self._write_backup(backup)
        return True
