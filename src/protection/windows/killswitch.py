"""斷線保護總開關：hosts 檔案 + WFP 動態規則（ADR-012、ADR-013）。"""

from src.connector.windows.sstp import PROFILE_NAME
from src.protection.windows.firewall import FirewallKillSwitch
from src.protection.windows.hosts import HostsFile
from src.protection.windows.wfp import WfpKillSwitch, interface_luid


def vpn_luid() -> int:
    return interface_luid(PROFILE_NAME)


class KillSwitch:
    def __init__(self, wfp=None, hosts=None, luid=vpn_luid, legacy_firewall=None) -> None:
        self.wfp = wfp or WfpKillSwitch()
        self.hosts = hosts or HostsFile()
        self.luid = luid
        self.legacy_firewall = legacy_firewall or FirewallKillSwitch()

    def engage(self, host_ips: dict[str, str]) -> None:
        """寫入 hosts（重連免 DNS）→ 開／更新 WFP 規則。失敗就全部撤掉再拋錯。

        找不到 VPN 介面時直接失敗：否則規則會把 VPN 本身也擋掉。
        """
        try:
            self.hosts.write_entries(host_ips)
            self.wfp.enable(sorted(set(host_ips.values())), self.luid())
        except Exception:
            self.release()
            raise

    def engage_apps(self, app_paths: list[str]) -> None:
        """Tor 模式：只放行指定程式（tor.exe）對外連線，其他全擋。不需要 hosts。"""
        try:
            self.wfp.enable([], None, app_paths=list(app_paths))
        except Exception:
            self.release()
            raise

    def release(self) -> None:
        """解除保護：先關 WFP（恢復上網），再清 hosts。兩步都盡量做完。"""
        errors = []
        for step in (self.wfp.disable, self.hosts.remove_entries):
            try:
                step()
            except Exception as exc:  # 一步失敗不影響另一步
                errors.append(str(exc))
        if errors:
            raise RuntimeError("；".join(errors))

    def cleanup(self) -> None:
        """App 啟動時：清掉殘留的 hosts 行，以及舊版（ADR-012 初版）可能留下的防火牆規則。

        WFP 動態規則不需要清：上次程式結束時 Windows 已自動刪除。
        """
        for step in (self.legacy_firewall.disable, self.hosts.remove_entries):
            try:
                step()
            except Exception:
                pass
