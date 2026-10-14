"""Qt-free solve time estimation and status formatting shared by GUI and CLI."""

from __future__ import annotations

import math


def format_elapsed(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_estimate(seconds: float) -> str:
    """Round an estimate to 5 s steps under a minute and whole minutes above."""
    step = 5 if seconds < 60 else 60
    return format_elapsed(max(step, math.floor(seconds / step + 0.5) * step))


def format_warm_up_status(message: str, elapsed_s: float, predicted_s: float | None = None) -> str:
    text = f"{message} · {format_elapsed(elapsed_s)}"
    if predicted_s is None:
        return text
    if elapsed_s > predicted_s:
        return f"{text} / longer than usual"
    return f"{text} / ~{format_estimate(predicted_s)}"


def format_solve_status(completed: int, total: int, elapsed_s: float, remaining_s: float | None) -> str:
    message = f"Solving {completed}/{total} · {format_elapsed(elapsed_s)} elapsed"
    if remaining_s is not None and completed < total:
        message += f" · ~{format_estimate(remaining_s)} left"
    return message


class SolveTimeEstimator:
    """Estimate remaining solve time from frequency result arrival times."""

    def __init__(self, total: int):
        self.total = total
        self._arrivals_s: list[float] = []

    @property
    def completed(self) -> int:
        return len(self._arrivals_s)

    def record_result(self, arrival_s: float) -> None:
        self._arrivals_s.append(arrival_s)

    def remaining_s(self) -> float | None:
        # The first gap contains pipeline fill, so frequency solve times start at the second.
        solve_times_s = [b - a for a, b in zip(self._arrivals_s[1:], self._arrivals_s[2:])]
        if len(solve_times_s) < 2:
            return None
        return sum(solve_times_s) / len(solve_times_s) * max(self.total - self.completed, 0)
