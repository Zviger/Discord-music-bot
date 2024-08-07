import logging

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    command_prefix: str = "-"
    app_name: str = "Music Bot"
    cached_music_dir: str = "./cached_music"
    config_file: str = "config.ini"
    arrow_up_small: str = "⬆️"
    arrow_down_small: str = "🔽"
    double_arrow_up_small: str = "⏫"
    double_arrow_down_small: str = "⏬"
    record_button: str = "⏺️"
    restart: bool = False


settings = Settings()

logger = logging.getLogger(settings.app_name)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(handler)
