import logging

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s"))

logger = logging.getLogger("music_bot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
