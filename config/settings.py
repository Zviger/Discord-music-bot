import configparser
from pathlib import Path

from pydantic_settings import BaseSettings

from core.models import UserSettings

root_path = Path().parent


class Settings(BaseSettings):
    command_prefix: str = "-"
    app_name: str = "Music Bot"
    cached_music_dir: Path = root_path / "cached_music"
    config_file: Path = root_path / "config.ini"
    cogs_path: Path = root_path / "bot" / "cogs"
    restart: bool = False
    users_settings: dict[int, UserSettings] = {}
    channels: dict[str, int] = {}
    bass_value: int = 0
    volume_value: int = 50
    tokens: dict = {}

    def __init__(self) -> None:
        super().__init__()
        self._config = configparser.ConfigParser()
        self.load_config()

    def load_config(self) -> None:
        self._config.read(self.config_file, encoding="utf-8")

        if self._config.has_section("music"):
            music_section = self._config["music"]
            self.bass_value = music_section.getint("bass") or 0
            self.volume_value = music_section.getint("volume") or 0

        if self._config.has_section("user_settings"):
            user_settings_section = self._config["user_settings"]
            for uid, setting in user_settings_section.items():
                self.users_settings[int(uid)] = UserSettings(*setting.strip().split("::"))

        if self._config.has_section("channels"):
            channels_section = self._config["channels"]
            for channel_name, channel_id in channels_section.items():
                self.channels[channel_name] = int(channel_id)

        if self._config.has_section("tokens"):
            tokens_section = self._config["tokens"]
            for token_name, token in tokens_section.items():
                self.tokens[token_name] = token

    def dump_config(self) -> None:
        self._config["music"] = {}
        self._config["music"]["bass"] = str(self.bass_value)
        self._config["music"]["volume"] = str(self.volume_value)

        with Path.open(Path(self.config_file), "w", encoding="utf-8") as config_file:
            self._config.write(config_file)
