import json
import os
import uuid
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

CONFIG_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

# 【扩充】官方预设主题包配置
THEMES = {
    "default_dark": {
        "name": "默认暗黑", "is_dark": True,
        "chat_bg_image": "", "sidebar_bg_image": "",
        "overlay_color": "rgba(0, 0, 0, 0)",
        "sidebar_bg": "#202020", "main_bg": "#202020", "input_bg": "#282828",
        "bubble_user_bg": "#2c5282", "bubble_ai_bg": "#333333", "text_color": "#e0e0e0"
    },
    "default_light": {
        "name": "默认明亮", "is_dark": False,
        "chat_bg_image": "", "sidebar_bg_image": "",
        "overlay_color": "rgba(0, 0, 0, 0)",
        "sidebar_bg": "#f3f3f3", "main_bg": "#f9f9f9", "input_bg": "#ffffff",
        "bubble_user_bg": "#2c5282", "bubble_ai_bg": "#ffffff", "text_color": "#000000"
    },
    "cyberpunk": {
        "name": "赛博朋克 (暗黑)", "is_dark": True,
        "chat_bg_image": "assets/themes/cyber_chat.jpg", 
        "sidebar_bg_image": "assets/themes/cyber_sidebar.jpg",
        "overlay_color": "rgba(10, 10, 20, 0.6)",
        "sidebar_bg": "rgba(10, 10, 20, 0.8)", "main_bg": "#0a0a14", "input_bg": "rgba(30, 30, 40, 0.8)",
        "bubble_user_bg": "rgba(138, 43, 226, 0.7)", "bubble_ai_bg": "rgba(20, 20, 30, 0.7)", "text_color": "#f0f0f0"
    },
    "minimal_paper": {
        "name": "极简纸张 (明亮)", "is_dark": False,
        "chat_bg_image": "assets/themes/paper_chat.jpg", 
        "sidebar_bg_image": "assets/themes/paper_sidebar.jpg",
        "overlay_color": "rgba(255, 255, 255, 0.4)",
        "sidebar_bg": "rgba(245, 245, 240, 0.9)", "main_bg": "#f5f5f0", "input_bg": "rgba(255, 255, 255, 0.8)",
        "bubble_user_bg": "rgba(44, 82, 130, 0.9)", "bubble_ai_bg": "rgba(255, 255, 255, 0.8)", "text_color": "#333333"
    }
}

# 【修复】移除重复的 DEFAULT_CONFIG 定义，只保留一个
DEFAULT_CONFIG = {
    "theme": "Dark",
    "current_theme": "default_dark",
    "current_api_id": "",
    "apis": []
}

class ConfigManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if not os.path.exists(CONFIG_PATH):
            self.config = DEFAULT_CONFIG
            self._save()
        else:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self._migrate_data() # 【新增】数据迁移

    def _migrate_data(self):
        """自动将旧版的字符串模型列表迁移为新版的能力字典，并补充思考控制字段"""
        changed = False
        for api in self.config.get("apis", []):
            models = api.get("models", [])
            if models and isinstance(models[0], str):
                api["models"] = [{"id": m, "name": m, "capabilities": [], "thinking_control": "none"} for m in models]
                changed = True
            else:
                for m in models:
                    if "thinking_control" not in m:
                        m["thinking_control"] = "none"
                        changed = True
        if changed:
            self._save()

    def _save(self):
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def get_theme(self): return self.config.get("theme", "Dark")
    def set_theme(self, theme): self.config["theme"] = theme; self._save()
    def get_apis(self): return self.config.get("apis", [])
    
    def get_current_api(self):
        apis = self.get_apis()
        current_id = self.config.get("current_api_id")
        for api in apis:
            if api["id"] == current_id: return api
        return apis[0] if apis else None

    def set_current_api(self, api_id): self.config["current_api_id"] = api_id; self._save()

    def add_api(self, name, base_url, api_key):
        api_id = str(uuid.uuid4())
        api = {"id": api_id, "name": name, "base_url": base_url, "api_key": api_key, "models": []}
        self.config.setdefault("apis", []).append(api)
        if not self.config.get("current_api_id"): self.config["current_api_id"] = api_id
        self._save()
        return api_id

    def update_api(self, api_id, name, base_url, api_key, models):
        for api in self.config.get("apis", []):
            if api["id"] == api_id:
                api.update({"name": name, "base_url": base_url, "api_key": api_key, "models": models})
                break
        self._save()

    def delete_api(self, api_id):
        self.config["apis"] = [a for a in self.config.get("apis", []) if a["id"] != api_id]
        if self.config.get("current_api_id") == api_id:
            self.config["current_api_id"] = self.config["apis"][0]["id"] if self.config["apis"] else ""
        self._save()

    def get_current_theme_config(self):
        theme_id = self.config.get("current_theme", "default_dark")
        return THEMES.get(theme_id, THEMES["default_dark"])

    def set_current_theme(self, theme_id):
        self.config["current_theme"] = theme_id
        self._save()