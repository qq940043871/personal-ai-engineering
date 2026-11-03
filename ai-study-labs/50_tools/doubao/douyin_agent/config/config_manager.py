import os
import yaml
from pathlib import Path


class ConfigManager:
    def __init__(self, config_dir=None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.yaml"
        self.config = self._load_config()

    def _load_config(self):
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return self._get_default_config()

    def _get_default_config(self):
        return {
            "volcengine": {
                "api_key": "your-api-key",
                "endpoint": "https://ark.cn-beijing.volces.com",
                "models": {
                    "llm": "ep-20250329164058-hq8tm",
                    "video": "ep-20250329164058-hq8tm"
                }
            },
            "video": {
                "duration": 20,
                "fps": 24,
                "ratio": "9:16",
                "max_retries": 10,
                "check_interval": 30
            },
            "image": {
                "width": 1024,
                "height": 1024,
                "model": "Doubao-Seedance-1.5-pro",
                "prompt": "high-quality"
            },
            "output": {
                "dir": "./output",
                "format": "mp4"
            }
        }

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)

    def get(self, key, default=None):
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key, value):
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self.save_config()

    def get_volcengine_config(self):
        return self.get('volcengine', {})

    def get_video_config(self):
        return self.get('video', {})

    def get_image_config(self):
        return self.get('image', {})

    def get_output_config(self):
        return self.get('output', {})