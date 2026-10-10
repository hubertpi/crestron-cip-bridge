# Version 0.1.22: dispatch entity updates on the Home Assistant event loop

Crestron CIP feedback can arrive on a protocol worker thread. All update notifications are now scheduled through Home Assistant's thread-safe job helper before dispatching to entities. This prevents `async_write_ha_state` from running off the event loop for lights, sensors, and discovered CIP entities.

# Version 0.1.21: keep display power state unknown

Display power switches remain stateless in Home Assistant because the AV3 provides no display power feedback. Each ON or OFF command returns the switch state to `unknown`; the assumed-state UI continues to provide explicit ON and OFF actions. This avoids a stale ON/OFF indication after presentation commands or iPad control.

# Version 0.1.20: add global presentation buttons

Adds five pressable buttons: Present Room PC, Present Showcase L, Present Showcase R, Present Table Input, and Presentation All Off. The four source buttons replay the captured global presentation command on Smart Object 20 (analog join 1 values 3–6, then digital joins 4013–4016). These are separate from the per-display input selectors on Smart Objects 75–78. The capture showed the AV clearing the selected source after Presentation All Off; its direct command sends CIP digital join 102, bypassing the iPad confirmation prompt. The off action has not yet been tested from HA.

# Version 0.1.19: add display input routing and projector lamp hours

Adds a neutral **Select Input** entity for each display (Projector, Sharp Touch, Sony TV Left, Sony TV Right). Captures for all four outputs confirm the same source command pattern: analog join 1 set to 3–6, followed by a momentary digital join 13–16 press/release for Room PC, Showcase L, Showcase R, and Table Input. The selector returns to **Select Input** after sending a command because source feedback was not observed in those captures. The iPad's label for the last source is “Table Input 1”; HA uses the requested “Table Input” label.

Adds a numeric Projector Lamp Hours sensor from top-level CIP serial join 25. The captured value was `1139`, observed in the same startup inventory as the `Projector` label; it had only one observed update, so live counter changes have not yet been demonstrated. No reset command is inferred.

# Version 0.1.18: add the other captured display commands

Adds command-assumed power switches for Projector (CIP ON/OFF joins 703/704), Sharp Touch (708/709), and Sony TV Right (714/715). Each ON/OFF pulse uses the press duration measured in the 0.1.17 proxy capture. The Projector's immediate AV3 echoes mirror the momentary command press/release and are not treated as display power feedback. All display states remain assumed from the last HA command and unknown after restart.

# Version 0.1.17: add Sony TV Left command switch

Adds a Sony TV Left power switch using the captured top-level CIP digital ON join 711 and OFF join 712. Each command is pulsed for approximately 35 ms to match the iPad capture. No AV3 feedback appeared in that capture, so the HA state is assumed from its last command and is unknown after restart; it is not a confirmed display power state. No joins are inferred for the other displays.

# Version 0.1.16: use wall-switch scene names

Keeps the verified Object 65 scene command joins and names the five scene buttons exactly as requested from the wall switch: All On, High, Med, Low, and Off. Coves control remains unverified; its observed scene feedback is not treated as proof of an individual control join.

# Crestron CIP Bridge for Home Assistant

A separate custom integration domain (`crestron_cip_bridge`) for monitoring and controlling panel-facing CIP joins on a Crestron AV3. It can coexist on disk with the older `crestron_av3_proxy` integration; avoid running both entries against the same AV3/IP ID simultaneously.

## Install

Copy `custom_components/crestron_cip_bridge` into Home Assistant's `custom_components` directory and restart Home Assistant. Add **Crestron CIP Bridge** from Devices & Services. The package includes `brand/icon.png` for Home Assistant versions that support local integration branding.

## Discover points

The integration records digital, analog, and serial values received in the AV3's CIP synchronization and feedback traffic. Open the integration's **Configure** menu and choose **Discover CIP points**, select a point, optionally send a test for a top-level digital/analog join, then assign a name and entity type. Newly configured entities are added after the options flow reloads the entry. The configured point's state follows later AV3 readback; commands do not invent state before feedback arrives.

The inventory covers points that the AV3 exposes through its CIP panel interface. It cannot enumerate hidden SIMPL program registers or values that the processor never sends. If no points appear, connect the iPad or allow the AV3's initial CIP synchronization to complete, then reopen discovery.

Top-level digital joins can be read as binary sensors or configured as switches/buttons. Top-level analog joins can be read as sensors or configured as number controls (raw range 0–65535). Serial and Smart Object values are currently read-only in generic discovery. Generic Smart Object writes are not implemented; the existing known Smart Object 61 lighting profile remains available in this separate build.

## Connection modes

- **Auto**: HA connects directly as CIP IP ID 03 and hands the connection to the iPad when it connects through HA's proxy listener, then returns to direct mode when the proxy session ends.
- **Proxy**: waits for the iPad and forwards its CIP session to the AV3.
- **Standalone**: HA connects directly; proxy listeners are not started.

Set the iPad app's AV3 host/port to Home Assistant's reachable address and the configured proxy CIP port when using Auto or Proxy. The optional HTTP proxy forwards the project traffic used by the app; its HA listener defaults to port 8001 (the AV3 upstream HTTP port remains 80).

## Smart Object 61 lights

Known light brightness follows AV3 analog readback, which represents the physical level. A brightness command never sets the entity to the requested value on its own. Feedback at brightness zero also marks the light off, even if an earlier digital report said on. After turn-on, HA restores the last AV3-confirmed level while waiting for any new analog readback. The six mapped lights use their own dimmer interaction joins: Pendant 4013 and Linear 4016 were directly observed in iPad captures; the remaining joins follow the same three-join pattern as their captured on/off joins and still need hardware confirmation. During a slider gesture, the integration holds the interaction join, sends the row selection once, streams analog brightness updates, then releases after the slider goes quiet. Coves is still unverified and brightness commands for it are disabled.

## Limits

Discovery is passive: it observes joins during startup synchronization and subsequent traffic. The initial inventory does not actively enumerate every possible join number. Test commands can operate real equipment, so identify a point before sending one. Analog controls send the raw 16-bit value and may need project-specific scaling.

## Diagnostics export (0.1.3)

After restarting HA, open the integration entry's three-dot menu and choose Download diagnostics. The JSON contains every currently observed join grouped by CIP/Smart Object, full serial strings, last-seen timestamps, configured entities, connection mode, and the known six-light Smart Object 61 mappings. No test commands or reconnects are sent during export.

Allow the AV3 to synchronize first; connecting the iPad through the proxy can provide additional observations. Inventory is held in memory and starts fresh on reload/restart. The download reflects the last received values; it is not a new poll of the AV3. Serial strings and assigned names are deliberately included for identification, so review the file before sharing.

## Object 61 naming preview (0.1.4)

Configure → Name known Object 61 lights previews the six received labels from serial joins 11, 13, 15, 17, 19, 21 against the existing row mappings. Submit to apply the names. This reuses existing light unique IDs and creates no duplicates. User-set HA name overrides take precedence; entity IDs are preserved. Names are saved in options so they survive restarts. No equipment commands are sent. This is an explicit Object 61 profile, not a general rule for other Smart Objects. Coves is not enabled without verification.
