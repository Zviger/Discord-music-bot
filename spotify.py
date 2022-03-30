import requests
import base64
import logging
import time

from settings import settings

logger = logging.getLogger(settings.app_name)


class SpotifyError(Exception):
    pass


class Spotify:
    OAUTH_TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1/"

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.get_token()  # validate token

    @staticmethod
    def _make_token_auth(client_id: str, client_secret: str) -> dict:
        auth_header = base64.b64encode((client_id + ":" + client_secret).encode("ascii"))
        return {"Authorization": "Basic %s" % auth_header.decode("ascii")}

    def get_track(self, uri: str) -> dict:
        """Get a track"s info from its URI"""
        return self.make_spotify_req(self.API_BASE + f"tracks/{uri}")

    def get_album(self, uri: str) -> dict:
        """Get an album"s info from its URI"""
        return self.make_spotify_req(self.API_BASE + f"albums/{uri}")

    def get_playlist(self, user: str, uri: str) -> dict:
        """Get a playlist"s info from its URI"""
        return self.make_spotify_req(self.API_BASE + f"users/{user}/playlists/{uri}")

    def get_playlist_tracks(self, uri: str) -> dict:
        """Get a list of a playlist's tracks"""
        return self.make_spotify_req(self.API_BASE + f"playlists/{uri}/tracks")

    def make_spotify_req(self, url: str) -> dict:
        """Proxy method for making a Spotify req using the correct Auth headers"""
        token = self.get_token()
        return self.make_get(url, headers={"Authorization": f"Bearer {token}"})

    @staticmethod
    def make_get(url: str, headers: dict = None) -> dict:
        """Makes a GET request and returns the results"""
        with requests.get(url, headers=headers) as r:
            if r.status_code != 200:
                raise SpotifyError(f"Issue making GET request to {url}: [{r.status_code}] {r.json()}")
            return r.json()

    @staticmethod
    def make_post(url: str, payload: dict, headers=None) -> dict:
        """Makes a POST request and returns the results"""
        with requests.post(url, data=payload, headers=headers) as r:
            if r.status_code != 200:
                raise SpotifyError(f"Issue making POST request to {url}: [{r.status_code}] {r.json()}")
            return r.json()

    def get_token(self) -> str:
        """Gets the token or creates a new one if expired"""
        if self.token and not self.check_token(self.token):
            return self.token["access_token"]

        token = self.request_token()
        if token is None:
            raise SpotifyError("Requested a token from Spotify, did not end up getting one")
        token["expires_at"] = int(time.time()) + token["expires_in"]
        self.token = token
        logger.debug(f"Created a new access token: {token}")
        return self.token["access_token"]

    @staticmethod
    def check_token(token: dict) -> bool:
        """Checks a token is valid"""
        now = int(time.time())
        return token["expires_at"] - now < 60

    def request_token(self) -> dict:
        """Obtains a token from Spotify and returns it"""
        payload = {"grant_type": "client_credentials"}
        headers = self._make_token_auth(self.client_id, self.client_secret)
        r = self.make_post(self.OAUTH_TOKEN_URL, payload=payload, headers=headers)
        return r
