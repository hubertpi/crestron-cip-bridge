# Crestron CIP Bridge

**AI authorship:** This integration was written by AI (OpenAI ChatGPT/Codex), with requirements, feedback, and hardware testing provided by the repository owner.

Home Assistant custom integration for monitoring and controlling verified Crestron AV3 CIP points. The integration source is stored in `custom_components/crestron_cip_bridge`.

## Install with HACS

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add https://github.com/hubertpi/crestron-cip-bridge as an **Integration**.
3. Open the Crestron CIP Bridge entry, choose a release, download it, then restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and select **Crestron CIP Bridge**.

Versions are published as GitHub releases. HACS installs and updates the integration from the repository release; this project does not publish a separate ZIP asset.

## Documentation

See [the integration README](custom_components/crestron_cip_bridge/README.md) for setup, connection modes, entity discovery, diagnostics, and current limitations. Commands operate real Crestron equipment; use only mappings identified for your AV3 project.

This is a community integration and is not affiliated with or endorsed by Crestron.

## Updates

When HACS offers a new Crestron CIP Bridge version, download the update and restart Home Assistant. Future revisions will update this repository and publish a matching GitHub release.

## Version 0.1.24

- Fixed the blank Error dialog when opening Connection settings or initial setup. Address fields now use a validator that Home Assistant can serialize for its forms.

## Version 0.1.25

- Added the read-only Active lighting scene sensor using AV3 Smart Object 65 feedback joins 4012, 4014, 4016, 4018, and 4020.
- The sensor preserves the last confirmed scene during false-before-true transitions, stays unknown without valid feedback, and clears its value when the AV3 connection drops.
- Diagnostics now report the manifest version dynamically. Standalone feedback and reconnect synchronization have not been physically tested.

## Version 0.1.23

- Configure → Connection settings lets you edit IP addresses, all CIP/HTTP ports, connection mode, and HTTP forwarding. Saving automatically reloads the connection.
- Removed the discovery, experimental-control, and known-object-naming options.
- Removed individual display power switches and input selectors, including automatic cleanup of those entities on existing installations.
- Lighting, scenes, global presentation buttons, existing generic entities, and diagnostics remain available.

