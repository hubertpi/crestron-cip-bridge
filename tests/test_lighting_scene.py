from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "custom_components" / "crestron_cip_bridge"),
)

from lighting_scene import ActiveLightingScene


class ActiveLightingSceneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scene = ActiveLightingScene()

    def update(self, join: int, value: bool, *, smart_object: int = 65):
        return SimpleNamespace(
            smart_object=smart_object,
            type="digital",
            join=join,
            value=value,
        )

    def test_false_before_new_true_holds_last_scene(self) -> None:
        self.assertFalse(self.scene.apply(self.update(4020, False)))
        self.assertIsNone(self.scene.state)

        self.assertTrue(self.scene.apply(self.update(4012, True)))
        self.assertEqual(self.scene.state, "All on")

        self.assertFalse(self.scene.apply(self.update(4012, False)))
        self.assertEqual(self.scene.state, "All on")

        self.assertTrue(self.scene.apply(self.update(4014, True)))
        self.assertEqual(self.scene.state, "High")

    def test_feedback_joins_use_wall_labels_and_ignore_other_updates(self) -> None:
        for join, expected in (
            (4012, "All on"),
            (4014, "High"),
            (4016, "Medium"),
            (4018, "Low"),
            (4020, "Off"),
        ):
            self.assertTrue(self.scene.apply(self.update(join, True)))
            self.assertEqual(self.scene.state, expected)

        self.assertFalse(self.scene.apply(self.update(4011, True)))
        self.assertFalse(self.scene.apply(self.update(4012, True, smart_object=61)))
        self.assertFalse(
            self.scene.apply(
                {"smart_object": 65, "type": "analog", "join": 4012, "value": 1}
            )
        )
        self.assertEqual(self.scene.state, "Off")

    def test_unknown_is_not_inferred_from_all_false_and_disconnect_resets(self) -> None:
        for join in (4012, 4014, 4016, 4018, 4020):
            self.assertFalse(self.scene.apply(self.update(join, False)))
        self.assertIsNone(self.scene.state)

        self.scene.apply(self.update(4016, True))
        self.assertEqual(self.scene.state, "Medium")
        self.assertTrue(self.scene.reset())
        self.assertIsNone(self.scene.state)
        self.assertFalse(self.scene.reset())


if __name__ == "__main__":
    unittest.main()
