"""State tracking for persistent AV3 lighting-scene feedback."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Smart Object 65 reports the selected wall-keypad scene on persistent digital
# joins. These feedback joins are distinct from the iPad command joins.
SCENE_FEEDBACK_JOINS = {
    4012: "All on",
    4014: "High",
    4016: "Medium",
    4018: "Low",
    4020: "Off",
}


class ActiveLightingScene:
    """Hold the last confirmed scene until another scene is positively selected.

    Scene transitions send the old selection false before the new selection
    true. False values therefore never clear or replace the current state. The
    caller resets this tracker when its AV3 connection drops.
    """

    def __init__(self) -> None:
        self.state: str | None = None

    def apply(self, update: Any) -> bool:
        """Apply a decoded AV3 feedback update; return whether state changed."""
        if isinstance(update, Mapping):
            get = update.get
        else:
            get = lambda key, default=None: getattr(update, key, default)

        if get("smart_object") != 65:
            return False
        join_type = get("type", "")
        join_type = getattr(join_type, "value", join_type)
        if not str(join_type).lower().startswith("d"):
            return False
        if get("value") is not True:
            return False

        scene = SCENE_FEEDBACK_JOINS.get(int(get("join", -1)))
        if scene is None or scene == self.state:
            return False
        self.state = scene
        return True

    def reset(self) -> bool:
        """Forget feedback on disconnect so a later session cannot show stale state."""
        if self.state is None:
            return False
        self.state = None
        return True
