# Crestron CIP Bridge

Home Assistant custom integration for monitoring and controlling verified Crestron AV3 CIP points. This repository contains the integration and its HACS release packages.

## Install with HACS

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add https://github.com/hubertpi/crestron-cip-bridge as an **Integration**.
3. Open the Crestron CIP Bridge entry, download it, then restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and select **Crestron CIP Bridge**.

Future versions are published as GitHub releases. HACS can install and update those releases from the integration page.

## Manual install

Download the latest Crestron_CIP_Bridge.zip from [Releases](https://github.com/hubertpi/crestron-cip-bridge/releases), extract custom_components/crestron_cip_bridge into Home Assistant's custom_components directory, and restart Home Assistant.

## Documentation

See [the integration README](custom_components/crestron_cip_bridge/README.md) for setup, connection modes, entity discovery, diagnostics, and current limitations. Commands operate real Crestron equipment; use only mappings identified for your AV3 project.

This is a community integration and is not affiliated with or endorsed by Crestron.
