"""Explicit project profiles, including the user-requested inferred Coves row."""
from .const import LIGHTS


def object61_candidates(points):
    """Combine known control rows with observed serial names, with mapping verification metadata."""
    candidates = []
    for light in LIGHTS:
        label_join = 9 + 2 * light['row']
        label = points.get(f'so61:serial:{label_join}', {}).get('value')
        if not isinstance(label, str) or not label.strip():
            continue
        candidates.append({
            'mapping_verified': light.get('mapping_verified', True),
            'key': light['key'], 'name': label.strip(), 'row': light['row'],
            'label_join': label_join, 'brightness_join': light['brightness_join'],
            'on_join': light['on_join'], 'off_join': light['off_join'],
            'brightness_observed': f"so61:analog:{light['brightness_join']}" in points,
        })
    return candidates
