"""更新／退版的背景工作與狀態（給 API 使用；實際下載與驗證在 src/core/updater.py）。"""

import threading
from pathlib import Path

from src.core import updater


class UpdateService:
    def __init__(self, exe_path: Path | None, on_installed=lambda tag: None, fetch=None, install=None) -> None:
        self.exe_path = exe_path  # None = 開發版（不是 exe），不支援程式內更新
        self.on_installed = on_installed
        self._fetch = fetch or updater.fetch_releases
        self._install = install or updater.install
        self._lock = threading.Lock()
        self._releases: list[dict] | None = None
        self._state = {"stage": "idle", "pct": 0, "message": "", "summary": None}

    def snapshot(self) -> dict:
        with self._lock:
            return {**self._state, "supported": self.exe_path is not None}

    def _set(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)

    def busy(self) -> bool:
        return self.snapshot()["stage"] in ("checking", "installing")

    def check(self, wait: bool = False) -> bool:
        if self.busy():
            return False
        self._set(stage="checking", pct=0, message="正在查詢版本…")

        def run():
            try:
                rels = self._fetch()
                with self._lock:
                    self._releases = rels
                self._set(stage="idle", message="", summary=updater.summarize(rels))
            except updater.UpdateError as exc:
                self._set(stage="error", message=str(exc))

        t = threading.Thread(target=run, daemon=True)
        t.start()
        if wait:
            t.join()
        return True

    def start_install(self, tag: str, wait: bool = False) -> str | None:
        """開始安裝；不能開始時回傳原因。"""
        if self.exe_path is None:
            return "開發版不支援程式內更新，請改用 exe"
        if self.busy():
            return "正在處理中，請稍候"
        with self._lock:
            rels = self._releases
        if not rels or not any(r.get("tag_name") == tag for r in rels):
            return "請先檢查版本"
        self._set(stage="installing", pct=0, message=f"正在下載 {tag}…")

        def run():
            try:
                self._install(tag, self.exe_path,
                              progress=lambda p: self._set(pct=p, message=f"正在下載 {tag}（{p}%）"),
                              releases=rels)
            except updater.UpdateError as exc:
                self._set(stage="error", message=str(exc))
                return
            except OSError as exc:
                self._set(stage="error", message=f"更新失敗：{exc}")
                return
            self._set(stage="restarting", pct=100, message=f"已安裝 {tag}（SHA256 核對通過），正在重新啟動…")
            self.on_installed(tag)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        if wait:
            t.join()
        return None
