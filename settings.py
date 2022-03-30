import logging

from pydantic import BaseSettings


class Settings(BaseSettings):
    command_prefix = "-"
    app_name = "Music Bot"
    cached_music_dir = "cached_music"
    config_file = "config.ini"
    arrow_up_small = b"\xf0\x9f\x94\xbc".decode("utf-8")
    arrow_down_small = b"\xf0\x9f\x94\xbd".decode("utf-8")
    double_arrow_up_small = b"\xe2\x8f\xab".decode("utf-8")
    double_arrow_down_small = b"\xe2\x8f\xac".decode("utf-8")
    record_button = b"\xe2\x8f\xba\xef\xb8\x8f".decode("utf-8")
    restart = False


settings = Settings()

logger = logging.getLogger(settings.app_name)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))
logger.addHandler(handler)
