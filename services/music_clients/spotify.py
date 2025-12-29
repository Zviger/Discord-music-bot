import base64
import logging
import time

import aiohttp

logger = logging.getLogger()


class SpotifyError(Exception):
    pass


class SpotifyMusicClient:
    OAUTH_TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105
    API_BASE = "https://api.spotify.com/v1/"

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: dict | None = None

    async def get_track(self, uri: str) -> dict:
        return await self.make_spotify_req(self.API_BASE + f"tracks/{uri}")

    async def get_album(self, uri: str) -> dict:
        return await self.make_spotify_req(self.API_BASE + f"albums/{uri}")

    async def get_playlist(self, user: str, uri: str) -> dict:
        return await self.make_spotify_req(self.API_BASE + f"users/{user}/playlists/{uri}")

    async def get_playlist_tracks(self, uri: str) -> dict:
        return await self.make_spotify_req(self.API_BASE + f"playlists/{uri}/tracks")

    async def make_spotify_req(self, url: str) -> dict:
        token = await self.get_token()
        return await self.make_request(url, headers={"Authorization": f"Bearer {token}"})

    @staticmethod
    async def make_request(
        url: str, method: str = "GET", data: dict | None = None, headers: dict | None = None
    ) -> dict:
        async with aiohttp.request(url=url, method=method, data=data, headers=headers) as r:
            if r.status != 200:
                msg = f"Issue making POST request to {url}: [{r.status}] {r.json()}"
                raise SpotifyError(msg)

            return await r.json()

    @staticmethod
    def _make_token_auth(client_id: str, client_secret: str) -> dict:
        auth_header = base64.b64encode((client_id + ":" + client_secret).encode("ascii"))
        return {"Authorization": "Basic {}".format(auth_header.decode("ascii"))}

    async def get_token(self) -> str:
        if self.token and not self.check_token(self.token):
            return self.token["access_token"]

        token = await self.request_token()
        if token is None:
            msg = "Requested a token from Spotify, did not end up getting one"
            raise SpotifyError(msg)
        token["expires_at"] = int(time.time()) + token["expires_in"]
        self.token = token
        logger.debug("Created a new access token: %s", str(token))
        return self.token["access_token"]

    @staticmethod
    def check_token(token: dict) -> bool:
        now = int(time.time())
        return token["expires_at"] - now < 60

    async def request_token(self) -> dict:
        payload = {"grant_type": "client_credentials"}
        headers = self._make_token_auth(self.client_id, self.client_secret)
        return await self.make_request(self.OAUTH_TOKEN_URL, method="POST", data=payload, headers=headers)
