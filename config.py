import configparser

from models import UserSettings
from settings import settings


class Config:
    def __init__(self) -> None:
        self.users_settings = {}
        self.channels = {}
        self.bass_value = 0
        self.volume_value = 50
        self.tokens = {}

        self.config = configparser.ConfigParser()
        self.load_config()

    def load_config(self) -> None:
        self.config.read(settings.config_file)

        if self.config.has_section("music"):
            music_section = self.config["music"]
            self.bass_value = music_section.getint("bass")
            self.volume_value = music_section.getint("volume")

        if self.config.has_section("user_settings"):
            user_settings_section = self.config["user_settings"]
            for uid, setting in user_settings_section.items():
                self.users_settings[int(uid)] = UserSettings(*setting.strip().split("::"))

        if self.config.has_section("channels"):
            channels_section = self.config["channels"]
            for channel_name, channel_id in channels_section.items():
                self.channels[channel_name] = int(channel_id)

        if self.config.has_section("tokens"):
            tokens_section = self.config["tokens"]
            for token_name, token in tokens_section.items():
                self.tokens[token_name] = token

    def dump_config(self) -> None:
        self.config["music"] = {}
        self.config["music"]["bass"] = str(self.bass_value)
        self.config["music"]["volume"] = str(self.volume_value)

        with open(settings.config_file, "w") as config_file:
            self.config.write(config_file)


config = Config()
