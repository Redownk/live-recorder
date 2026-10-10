from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic


@dataclass
class RecordingSession:
    log_id: int
    started_at: str
    started_monotonic: float
    state: str = "recording"


class RecordingStatusTracker:
    def __init__(self):
        self.sessions: dict[int, RecordingSession] = {}

    def started(self, room_id: int, log_id: int):
        session = self.sessions.get(room_id)
        if session is not None and session.log_id == log_id:
            session.state = "recording"
            return
        self.sessions[room_id] = RecordingSession(
            log_id=log_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            started_monotonic=monotonic(),
        )

    def reconnecting(self, room_id: int, log_id: int):
        session = self.sessions.get(room_id)
        if session is not None and session.log_id == log_id:
            session.state = "reconnecting"

    def finished(self, room_id: int, log_id: int):
        session = self.sessions.get(room_id)
        if session is not None and session.log_id == log_id:
            del self.sessions[room_id]

    def snapshot(self):
        now = monotonic()
        return {
            room_id: {
                "state": session.state,
                "log_id": session.log_id,
                "started_at": session.started_at,
                "elapsed_seconds": max(0, int(now - session.started_monotonic)),
            }
            for room_id, session in self.sessions.items()
        }


def get_recording_status(app) -> RecordingStatusTracker:
    tracker = getattr(app.state, "recording_status", None)
    if tracker is None:
        tracker = RecordingStatusTracker()
        app.state.recording_status = tracker
    return tracker
