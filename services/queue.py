import random

from core.models import Track


class QueueManager:
    def __init__(self) -> None:
        self._queue: list[Track] = []
        self._current_index: int = -1
        self._last_used_index: int = -1
        self._interrupting_track: Track | None = None
        self._is_looped: bool = False
        self._before_interruption_index: int = -1

    def add_many(self, tracks: list[Track]) -> None:
        self._queue.extend(tracks)

    def add_interruption(self, track: Track) -> None:
        self._interrupting_track = track

    def clear(self) -> None:
        self._queue.clear()
        self._current_index = -1
        self._last_used_index = -1
        self._interrupting_track = None
        self._before_interruption_index = -1

    def get_next(self) -> Track | None:
        next_index = self._get_next_index()

        if self._interrupting_track is not None:
            self._interrupting_track = None

        self._current_index = next_index

        if next_index != -1:
            self._last_used_index = self._current_index

            return self._queue[next_index]

        return None

    def try_get_next(self) -> Track | None:
        if self._get_next_index() != -1:
            return self.get_next()

        return None

    def get_prev(self) -> Track | None:
        prev_index = self._get_prev_index()

        if self._interrupting_track is not None:
            self._interrupting_track = None

        self._current_index = prev_index

        if prev_index != -1:
            self._last_used_index = self._current_index

            return self._queue[prev_index]

        return None

    def try_get_prev(self) -> Track | None:
        if self._get_prev_index() != -1:
            return self.get_prev()

        return None

    def get_current(self) -> Track | None:
        if self._interrupting_track is not None:
            return self._interrupting_track

        if self._current_index != -1:
            return self._queue[self._current_index]

        return None

    def get_many(self, limit: int, offset: int = 0) -> list[Track]:
        return self._queue[offset : limit + offset]

    def jump_to(self, index: int) -> Track | None:
        if index < 0:
            index += self.get_queue_length()

        if index < self.get_queue_length():
            self._current_index = index
            self._before_interruption_index = 0
            self._interrupting_track = None

            return self._queue[index]

        return None

    def remove_at(self, index: int) -> Track | None:
        if 0 <= index < self.get_queue_length():
            removed = self._queue.pop(index)
            if index <= self._current_index:
                self._current_index -= 1

            return removed
        return None

    def get_current_index(self) -> int:
        return self._current_index

    def get_queue_length(self) -> int:
        return len(self._queue)

    def get_interrupting(self) -> Track | None:
        return self._interrupting_track

    def toggle_loop(self) -> bool:
        self._is_looped = not self._is_looped

        return self._is_looped

    def shuffle(self) -> None:
        if self._current_index > 0:
            current = self._queue.pop(self._current_index)
            random.shuffle(self._queue)
            self._queue.insert(0, current)
            self._current_index = 0

            if self._before_interruption_index != -1:
                self._before_interruption_index = 0
        else:
            random.shuffle(self._queue)

    def _get_next_index(self) -> int:
        if self._interrupting_track is not None and self._current_index != -1:
            return self._current_index

        if self._current_index != -1:
            next_index = self._current_index + 1

            if next_index >= self.get_queue_length() and self._is_looped:
                return 0

            if next_index < self.get_queue_length():
                return next_index

        if self._last_used_index == -1:
            return 0

        if self._last_used_index + 1 < self.get_queue_length():
            return self._last_used_index + 1

        return -1

    def _get_prev_index(self) -> int:
        if self._interrupting_track is not None and self._current_index != -1:
            return self._current_index

        if self._current_index != -1:
            prev_index = self._current_index - 1

            if prev_index < 0 and self._is_looped:
                return self.get_queue_length() - 1

            if prev_index >= 0:
                return prev_index

        return -1
