"""Bounded passive commissioning recordings; never transmit commands."""
from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic


def now():
    return datetime.now(timezone.utc).isoformat()


class ActionCapture:
    def __init__(self, limit=2000, duration=300):
        self.limit = limit
        self.duration = duration
        self.active = False
        self.data = {"status": "not_started", "events": []}

    def start(self, label, points, mode):
        self.active = True
        self.deadline = monotonic() + self.duration
        self.data = {"status": "recording", "label": label[:120], "started_at": now(),
                     "starting_mode": mode, "starting_inventory": deepcopy(list(points.values())),
                     "events": [], "event_limit": self.limit, "duration_limit_seconds": self.duration}

    def stop(self, reason="stopped_by_user"):
        if self.active:
            self.active = False
            self.data.update(status=reason, stopped_at=now())

    def record(self, direction, mode, updates, frame=None):
        if not self.active:
            return
        if monotonic() >= self.deadline:
            self.stop("time_limit_reached")
            return
        event = {"sequence": len(self.data["events"]) + 1, "at": now(),
                 "direction": direction, "mode": mode, "updates": deepcopy(updates)}
        if frame is not None:
            event["frame_hex"] = frame.hex()
        self.data["events"].append(event)
        if len(self.data["events"]) >= self.limit:
            self.stop("event_limit_reached")

    def snapshot(self):
        if self.active and monotonic() >= self.deadline:
            self.stop("time_limit_reached")
        result = deepcopy(self.data)
        result["ipad_event_count"] = sum(e["direction"] == "ipad_to_av3" for e in result["events"])
        return result
