import aiohttp
import asyncio
import base64
import logging
import time

from aiohttp import ClientSession

from settings import settings

logger = logging.getLogger(settings.app_name)


class SpotifyError(Exception):
    pass


class Spotify:
    OAUTH_TOKEN_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1/"

    def __init__(self, client_id: str, client_secret: str, aiosession: ClientSession = None, loop=None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.aiosession = aiosession if aiosession else aiohttp.ClientSession()
        self.loop = loop if loop else asyncio.get_event_loop()

        self.token = None

        self.loop.create_task(self.get_token())  # validate token

    @staticmethod
    def _make_token_auth(client_id: str, client_secret: str) -> dict:
        auth_header = base64.b64encode((client_id + ":" + client_secret).encode("ascii"))
        return {"Authorization": "Basic %s" % auth_header.decode("ascii")}

    async def get_track(self, uri: str) -> dict:
        """Get a track"s info from its URI"""
        return await self.make_spotify_req(self.API_BASE + f"tracks/{uri}")

    async def get_album(self, uri: str) -> dict:
        """Get an album"s info from its URI"""
        return await self.make_spotify_req(self.API_BASE + f"albums/{uri}")

    async def get_playlist(self, user: str, uri: str) -> dict:
        """Get a playlist"s info from its URI"""
        return await self.make_spotify_req(self.API_BASE + f"users/{user}/playlists/{uri}")

    async def get_playlist_tracks(self, uri: str) -> dict:
        """Get a list of a playlist's tracks"""
        return await self.make_spotify_req(self.API_BASE + f"playlists/{uri}/tracks")

    async def make_spotify_req(self, url: str) -> dict:
        """Proxy method for making a Spotify req using the correct Auth headers"""
        token = await self.get_token()
        return await self.make_get(url, headers={"Authorization": f"Bearer {token}"})

    async def make_get(self, url: str, headers: dict = None) -> dict:
        """Makes a GET request and returns the results"""
        async with self.aiosession.get(url, headers=headers) as r:
            if r.status != 200:
                raise SpotifyError(f"Issue making GET request to {url}: [{r.status}] {await r.json()}")
            return await r.json()

    async def make_post(self, url: str, payload: dict, headers=None) -> dict:
        """Makes a POST request and returns the results"""
        async with self.aiosession.post(url, data=payload, headers=headers) as r:
            if r.status != 200:
                raise SpotifyError(f"Issue making POST request to {url}: [{r.status}] {await r.json()}")
            return await r.json()

    async def get_token(self) -> str:
        """Gets the token or creates a new one if expired"""
        if self.token and not await self.check_token(self.token):
            return self.token["access_token"]

        token = await self.request_token()
        if token is None:
            raise SpotifyError("Requested a token from Spotify, did not end up getting one")
        token["expires_at"] = int(time.time()) + token["expires_in"]
        self.token = token
        logger.debug(f"Created a new access token: {token}")
        return self.token["access_token"]

    @staticmethod
    async def check_token(token: dict) -> bool:
        """Checks a token is valid"""
        now = int(time.time())
        return token["expires_at"] - now < 60

    async def request_token(self) -> dict:
        """Obtains a token from Spotify and returns it"""
        payload = {"grant_type": "client_credentials"}
        headers = self._make_token_auth(self.client_id, self.client_secret)
        r = await self.make_post(self.OAUTH_TOKEN_URL, payload=payload, headers=headers)
        return r
