"""Kill switch：Windows Filtering Platform（WFP）動態規則（ADR-013）。

為什麼用 WFP「動態工作階段」：
  規則跟著本程式的工作階段存活。程式正常結束、當掉、被強制關閉時，Windows 會自動刪除這些規則，
  所以不會有「App 當掉後網路被鎖住」的問題（市售 VPN 的做法）。

結構定義與 GUID 對照 WireGuard for Windows 原始碼（tunnel/firewall/types_windows*.go，MIT）
與 Microsoft 文件；結構大小有單元測試把關。只支援 64 位元 Windows。

規則（同一個子層內，權重高的先比對，第一個符合的決定結果）：
  15 允許 本機迴路
  14 允許 VPN 介面（依介面 LUID）
  13 封鎖 DNS（遠端 port 53、853）── 只會擋到「不走 VPN」的 DNS
  12 允許 VPN 伺服器 IP（SSTP 本身的連線）；允許指定程式（Tor 模式：tor.exe）
  11 允許 區域網路、多播、廣播（IPv4）；連結本機、多播（IPv6）
   0 封鎖 其他全部
"""

import ctypes
import ipaddress
import threading
import uuid
from ctypes import POINTER, Structure, Union, byref, c_int32, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p, c_wchar_p

from src.protection.ranges import IPV4_ALWAYS_ALLOWED

# ---- 常數 ----
RPC_C_AUTHN_WINNT = 10
FWPM_SESSION_FLAG_DYNAMIC = 0x1
INFINITE = 0xFFFFFFFF

FWP_UINT8, FWP_UINT16, FWP_UINT32, FWP_UINT64 = 1, 2, 3, 4
FWP_BYTE_BLOB_TYPE = 12
FWP_V4_ADDR_MASK, FWP_V6_ADDR_MASK = 0x100, 0x101

FWP_MATCH_EQUAL = 0
FWP_MATCH_FLAGS_ALL_SET = 6

FWP_ACTION_BLOCK = 0x1001
FWP_ACTION_PERMIT = 0x1002
FWP_CONDITION_FLAG_IS_LOOPBACK = 0x1

LAYER_CONNECT_V4 = uuid.UUID("c38d57d1-05a7-4c33-904f-7fbceee60e82")
LAYER_CONNECT_V6 = uuid.UUID("4a72393b-319f-44bc-84c3-ba54dcb3b6b4")
COND_FLAGS = uuid.UUID("632ce23b-5167-435c-86d7-e903684aa80c")
COND_LOCAL_INTERFACE = uuid.UUID("4cd62a49-59c3-4969-b7f3-bda5d32890a4")
COND_REMOTE_ADDRESS = uuid.UUID("b235ae9a-1d64-49b8-a44c-5ff3d9095045")
COND_REMOTE_PORT = uuid.UUID("c35a604d-d22b-4e1a-91b4-68f674ee674b")
COND_ALE_APP_ID = uuid.UUID("d78e1e87-8644-4ea5-9437-d809ecefc971")

IPV6_ALLOWED = ["fe80::/10", "ff00::/8"]  # 鄰居探索等必要流量
DNS_PORTS = (53, 853)


# ---- 結構（x64 版面，與 WireGuard 的 *_Size 常數一致）----
class GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16), ("Data4", c_uint8 * 8)]

    @classmethod
    def of(cls, u: uuid.UUID) -> "GUID":
        return cls.from_buffer_copy(u.bytes_le)


class DISPLAY_DATA(Structure):
    _fields_ = [("name", c_wchar_p), ("description", c_wchar_p)]


class BYTE_BLOB(Structure):
    _fields_ = [("size", c_uint32), ("data", c_void_p)]


class VALUE(Structure):  # FWP_VALUE0 / FWP_CONDITION_VALUE0：型別 + 8 bytes 聯集
    _fields_ = [("type", c_uint32), ("value", c_uint64)]


class FILTER_CONDITION(Structure):
    _fields_ = [("fieldKey", GUID), ("matchType", c_uint32), ("conditionValue", VALUE)]


class ACTION(Structure):
    _fields_ = [("type", c_uint32), ("filterType", GUID)]


class _CONTEXT(Union):
    _fields_ = [("rawContext", c_uint64), ("providerContextKey", GUID)]


class FILTER(Structure):
    _fields_ = [
        ("filterKey", GUID), ("displayData", DISPLAY_DATA), ("flags", c_uint32), ("providerKey", c_void_p),
        ("providerData", BYTE_BLOB), ("layerKey", GUID), ("subLayerKey", GUID), ("weight", VALUE),
        ("numFilterConditions", c_uint32), ("filterCondition", c_void_p), ("action", ACTION),
        ("context", _CONTEXT), ("reserved", c_void_p), ("filterId", c_uint64), ("effectiveWeight", VALUE),
    ]


class SESSION(Structure):
    _fields_ = [
        ("sessionKey", GUID), ("displayData", DISPLAY_DATA), ("flags", c_uint32), ("txnWaitTimeoutInMSec", c_uint32),
        ("processId", c_uint32), ("sid", c_void_p), ("username", c_wchar_p), ("kernelMode", c_int32),
    ]


class SUBLAYER(Structure):
    _fields_ = [
        ("subLayerKey", GUID), ("displayData", DISPLAY_DATA), ("flags", c_uint32), ("providerKey", c_void_p),
        ("providerData", BYTE_BLOB), ("weight", c_uint16),
    ]


class V4_ADDR_AND_MASK(Structure):
    _fields_ = [("addr", c_uint32), ("mask", c_uint32)]


class V6_ADDR_AND_MASK(Structure):
    _fields_ = [("addr", c_uint8 * 16), ("prefixLength", c_uint8)]


# ---- 條件建構（keep 用來保存指標指向的物件，呼叫 API 前不能被回收）----
def _cond(key: uuid.UUID, match: int, vtype: int, value: int) -> FILTER_CONDITION:
    return FILTER_CONDITION(GUID.of(key), match, VALUE(vtype, value))


def _ptr_cond(key, match, vtype, obj, keep: list) -> FILTER_CONDITION:
    keep.append(obj)
    return _cond(key, match, vtype, ctypes.addressof(obj))


def v4_net_condition(cidr: str, keep: list) -> FILTER_CONDITION:
    net = ipaddress.IPv4Network(cidr)
    obj = V4_ADDR_AND_MASK(int(net.network_address), int(net.netmask))  # 主機位元組順序
    return _ptr_cond(COND_REMOTE_ADDRESS, FWP_MATCH_EQUAL, FWP_V4_ADDR_MASK, obj, keep)


def v6_net_condition(cidr: str, keep: list) -> FILTER_CONDITION:
    net = ipaddress.IPv6Network(cidr)
    obj = V6_ADDR_AND_MASK((c_uint8 * 16)(*net.network_address.packed), net.prefixlen)
    return _ptr_cond(COND_REMOTE_ADDRESS, FWP_MATCH_EQUAL, FWP_V6_ADDR_MASK, obj, keep)


def v4_host_condition(ip: str) -> FILTER_CONDITION:
    return _cond(COND_REMOTE_ADDRESS, FWP_MATCH_EQUAL, FWP_UINT32, int(ipaddress.IPv4Address(ip)))


def luid_condition(luid: int, keep: list) -> FILTER_CONDITION:
    return _ptr_cond(COND_LOCAL_INTERFACE, FWP_MATCH_EQUAL, FWP_UINT64, c_uint64(luid), keep)


def interface_luid(alias: str) -> int:
    """依介面名稱（例如 AIXAI-VPN-SSTP）取得 LUID；找不到就拋 OSError。"""
    luid = c_uint64()
    rc = ctypes.windll.iphlpapi.ConvertInterfaceAliasToLuid(c_wchar_p(alias), byref(luid))
    if rc != 0:
        raise OSError(f"找不到網路介面 {alias}（錯誤碼 {rc}）")
    return luid.value


class WfpError(OSError):
    pass


class WfpKillSwitch:
    """一個動態工作階段 = 一組規則。release() 或程式結束時，規則全部自動消失。"""

    def __init__(self) -> None:
        self._lib = None
        self._engine = c_void_p()
        self._sublayer = GUID.of(uuid.uuid4())
        self._dynamic_ids: list[int] = []  # 會隨重連更新的規則（VPN 介面、伺服器 IP）
        self._lock = threading.Lock()

    # ---- 低階呼叫 ----
    def _api(self):
        if self._lib is None:
            if ctypes.sizeof(c_void_p) != 8:
                raise WfpError("只支援 64 位元 Windows")
            lib = ctypes.WinDLL("fwpuclnt.dll")
            for name in ("FwpmEngineOpen0", "FwpmEngineClose0", "FwpmSubLayerAdd0", "FwpmFilterAdd0",
                         "FwpmGetAppIdFromFileName0",
                         "FwpmFilterDeleteById0", "FwpmTransactionBegin0", "FwpmTransactionCommit0",
                         "FwpmTransactionAbort0"):
                getattr(lib, name).restype = c_uint32
            lib.FwpmEngineOpen0.argtypes = [c_wchar_p, c_uint32, c_void_p, POINTER(SESSION), POINTER(c_void_p)]
            lib.FwpmEngineClose0.argtypes = [c_void_p]
            lib.FwpmSubLayerAdd0.argtypes = [c_void_p, POINTER(SUBLAYER), c_void_p]
            lib.FwpmFilterAdd0.argtypes = [c_void_p, POINTER(FILTER), c_void_p, POINTER(c_uint64)]
            lib.FwpmFilterDeleteById0.argtypes = [c_void_p, c_uint64]
            lib.FwpmTransactionBegin0.argtypes = [c_void_p, c_uint32]
            lib.FwpmTransactionCommit0.argtypes = [c_void_p]
            lib.FwpmTransactionAbort0.argtypes = [c_void_p]
            lib.FwpmGetAppIdFromFileName0.argtypes = [c_wchar_p, POINTER(c_void_p)]
            lib.FwpmFreeMemory0.argtypes = [POINTER(c_void_p)]
            lib.FwpmFreeMemory0.restype = None
            self._lib = lib
        return self._lib

    @staticmethod
    def _check(rc: int, what: str) -> None:
        if rc != 0:
            raise WfpError(f"{what} 失敗（錯誤碼 0x{rc:08X}）")

    def _add_filter(self, name: str, layer: uuid.UUID, weight: int, action: int,
                    conditions: list[FILTER_CONDITION]) -> int:
        arr = (FILTER_CONDITION * len(conditions))(*conditions) if conditions else None
        f = FILTER()
        f.displayData = DISPLAY_DATA(f"AIXAI-VPN {name}", "AIXAI-VPN kill switch")
        f.layerKey = GUID.of(layer)
        f.subLayerKey = self._sublayer
        f.weight = VALUE(FWP_UINT8, weight)
        f.numFilterConditions = len(conditions)
        f.filterCondition = ctypes.addressof(arr) if arr is not None else None
        f.action = ACTION(action, GUID())
        fid = c_uint64()
        self._check(self._api().FwpmFilterAdd0(self._engine, byref(f), None, byref(fid)), f"新增規則 {name}")
        return fid.value

    def _transaction(self, body) -> None:
        api = self._api()
        self._check(api.FwpmTransactionBegin0(self._engine, 0), "開始交易")
        try:
            body()
        except Exception:
            api.FwpmTransactionAbort0(self._engine)
            raise
        self._check(api.FwpmTransactionCommit0(self._engine), "提交交易")

    def _app_condition(self, path: str, keep: list) -> FILTER_CONDITION:
        """程式路徑 → WFP 的 App ID（裝置路徑格式），用來只放行特定程式。"""
        blob_ptr = c_void_p()
        self._check(self._api().FwpmGetAppIdFromFileName0(path, byref(blob_ptr)), f"取得程式識別 {path}")
        try:
            src = BYTE_BLOB.from_address(blob_ptr.value)
            data = (c_uint8 * src.size).from_buffer_copy(ctypes.string_at(src.data, src.size))
            blob = BYTE_BLOB(src.size, ctypes.addressof(data))
            keep.extend([data, blob])
        finally:
            self._api().FwpmFreeMemory0(byref(blob_ptr))
        return _ptr_cond(COND_ALE_APP_ID, FWP_MATCH_EQUAL, FWP_BYTE_BLOB_TYPE, blob, keep)

    # ---- 規則內容 ----
    def _add_dynamic(self, server_ips: list[str], vpn_luid: int | None, app_paths: list[str] = ()) -> list[int]:
        keep: list = []
        ids = []
        for path in app_paths:
            for layer in (LAYER_CONNECT_V4, LAYER_CONNECT_V6):
                ids.append(self._add_filter("permit app", layer, 12, FWP_ACTION_PERMIT,
                                            [self._app_condition(path, keep)]))
        if vpn_luid is not None:
            for layer in (LAYER_CONNECT_V4, LAYER_CONNECT_V6):
                ids.append(self._add_filter("permit VPN interface", layer, 14, FWP_ACTION_PERMIT,
                                            [luid_condition(vpn_luid, keep)]))
        if server_ips:
            ids.append(self._add_filter("permit VPN servers", LAYER_CONNECT_V4, 12, FWP_ACTION_PERMIT,
                                        [v4_host_condition(ip) for ip in server_ips]))
        return ids

    def _add_static(self) -> None:
        keep: list = []
        loopback = [_cond(COND_FLAGS, FWP_MATCH_FLAGS_ALL_SET, FWP_UINT32, FWP_CONDITION_FLAG_IS_LOOPBACK)]
        dns = [_cond(COND_REMOTE_PORT, FWP_MATCH_EQUAL, FWP_UINT16, p) for p in DNS_PORTS]  # 同欄位的條件 = 「或」
        for layer in (LAYER_CONNECT_V4, LAYER_CONNECT_V6):
            self._add_filter("permit loopback", layer, 15, FWP_ACTION_PERMIT, loopback)
            self._add_filter("block DNS", layer, 13, FWP_ACTION_BLOCK, dns)
            self._add_filter("block all", layer, 0, FWP_ACTION_BLOCK, [])
        self._add_filter("permit LAN v4", LAYER_CONNECT_V4, 11, FWP_ACTION_PERMIT,
                         [v4_net_condition(c, keep) for c in IPV4_ALWAYS_ALLOWED if c != "127.0.0.0/8"])
        self._add_filter("permit link-local v6", LAYER_CONNECT_V6, 11, FWP_ACTION_PERMIT,
                         [v6_net_condition(c, keep) for c in IPV6_ALLOWED])

    # ---- 對外介面 ----
    def is_active(self) -> bool:
        return bool(self._engine.value)

    def enable(self, server_ips: list[str], vpn_luid: int | None, app_paths: list[str] = ()) -> None:
        """第一次呼叫：建立動態工作階段與全部規則。之後呼叫：只更新 VPN 介面與伺服器 IP（無空窗）。"""
        for ip in server_ips:
            ipaddress.IPv4Address(ip)  # 先驗證，不合法直接拋錯
        with self._lock:
            if not self.is_active():
                self._open_and_install(server_ips, vpn_luid, app_paths)
                return
            old = self._dynamic_ids

            def update():
                new = self._add_dynamic(server_ips, vpn_luid, app_paths)  # 先加新的再刪舊的 → 不會有空窗
                for fid in old:
                    self._check(self._api().FwpmFilterDeleteById0(self._engine, fid), "刪除舊規則")
                self._dynamic_ids = new

            self._transaction(update)

    def _open_and_install(self, server_ips, vpn_luid, app_paths=()) -> None:
        api = self._api()
        session = SESSION()
        session.displayData = DISPLAY_DATA("AIXAI-VPN", "AIXAI-VPN dynamic session")
        session.flags = FWPM_SESSION_FLAG_DYNAMIC
        session.txnWaitTimeoutInMSec = INFINITE
        engine = c_void_p()
        self._check(api.FwpmEngineOpen0(None, RPC_C_AUTHN_WINNT, None, byref(session), byref(engine)), "開啟 WFP")
        self._engine = engine

        def install():
            sub = SUBLAYER()
            sub.subLayerKey = self._sublayer
            sub.displayData = DISPLAY_DATA("AIXAI-VPN", "AIXAI-VPN kill switch")
            sub.weight = 0xFFFF
            self._check(api.FwpmSubLayerAdd0(self._engine, byref(sub), None), "新增子層")
            self._add_static()
            self._dynamic_ids = self._add_dynamic(server_ips, vpn_luid, app_paths)

        try:
            self._transaction(install)
        except Exception:
            self._close()
            raise

    def _close(self) -> None:
        if self.is_active():
            self._api().FwpmEngineClose0(self._engine)  # 動態工作階段關閉 → 規則全部自動刪除
        self._engine = c_void_p()
        self._dynamic_ids = []

    def disable(self) -> None:
        with self._lock:
            self._close()
