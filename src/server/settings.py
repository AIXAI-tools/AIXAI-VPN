"""使用者設定（研究模式、已同意的條款版本、啟動時檢查更新），存在 %LOCALAPPDATA%\\AIXAI-VPN\\settings.json。"""

import json
import os
from pathlib import Path

SETTINGS_PATH = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AIXAI-VPN" / "settings.json"
DEFAULTS = {"research_mode": False, "terms_accepted": "", "auto_update_check": True}


class Settings:
    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path
        self.data = dict(DEFAULTS)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.data.update({k: loaded[k] for k in DEFAULTS if isinstance(loaded.get(k), type(DEFAULTS[k]))})
        except (OSError, ValueError, AttributeError):
            pass  # 沒有檔案或壞掉 → 用預設值

    def get(self, key: str):
        return self.data[key]

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS or not isinstance(value, type(DEFAULTS[key])):
            raise ValueError(f"不支援的設定：{key}")
        self.data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        tmp.replace(self.path)
