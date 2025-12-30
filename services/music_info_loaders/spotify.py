from urllib import parse

from core.exceptions import CantLoadTrackInfoError
from services.api_clients.spotify import SpotifyApiClient


class SpotifyInfoLoader:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client = SpotifyApiClient(client_id=client_id, client_secret=client_secret)

    async def get_track_names(self, source: str) -> list[str]:
        parsed_url = parse.urlparse(source)
        path_args = parsed_url.path.split("/")

        if "track" in path_args:
            response = await self._client.get_track(path_args[-1])

            return [f"{response['artists'][0]['name']} {response['name']}"]

        if "album" in path_args:
            response = await self._client.get_album(path_args[-1])

            return [f"{i['name']} {i['artists'][0]['name']}" for i in response["tracks"]["items"]]

        if "playlist" in path_args:
            tracks = []
            response = await self._client.get_playlist_tracks(path_args[-1])
            while True:
                tracks.extend(response["items"])

                if response["next"] is not None:
                    response = await self._client.make_spotify_req(response["next"])
                    continue

                break

            return [f"{i['track']['name']} {i['track']['artists'][0]['name']}" for i in tracks]

        msg = "Can't load track's spotify info"
        raise CantLoadTrackInfoError(msg)
