# Fitorb Smart Ring Home Assistant Integration Design

## Goal

Build a Home Assistant custom integration that exposes current data from a Fitorb smart ring as Home Assistant sensors. The ring appears to be compatible with the Colmi R02-R06 BLE protocol. Version 1 focuses on stable current values; historical sync, sleep import, and long time-series backfill are intentionally deferred.

## Context

The Home Assistant instance runs in a Proxmox VM. A USB Bluetooth dongle can be passed through to the VM and used by Home Assistant's Bluetooth integration. Shelly Gen 2+ devices in the home can forward Bluetooth advertisements, but they cannot proxy active GATT connections, so they are not suitable for this ring integration. The phone app does not need to stay connected while Home Assistant reads the ring.

Relevant upstream references:

- `YannisDC/ColmiSmartRing`: open app work and references around Colmi smart ring data.
- `edgeimpulse/example-data-collection-colmi-r02`: Python/Bleak script for raw data logging from Colmi R02.
- `CitizenOneX/colmi_r06_fbp`: Dart protocol notes and parsers for Colmi R02-R06 commands and notifications.
- Home Assistant developer documentation for Bluetooth config flows, active Bluetooth coordinators, config entries, and sensor entities.

## Recommended Approach

Use a native Home Assistant custom integration named `fitorb`.

Home Assistant will act as the active BLE client. It discovers or manually configures the ring, opens short GATT sessions on a controlled interval, sends Colmi-compatible commands, parses notifications, and exposes the resulting values as Home Assistant entities.

This avoids a separate daemon or MQTT bridge, keeps all data local, and leaves a clean path to add historical sync later.

## Hardware And Setup Assumptions

- Home Assistant has the official Bluetooth integration enabled.
- The USB Bluetooth adapter is passed through from Proxmox to the Home Assistant VM.
- The adapter supports active BLE scanning and GATT connections.
- The ring can be disconnected from the phone app when Home Assistant needs to poll it.
- The integration handles the ring being asleep, charging, out of range, or temporarily connected to another client.

## Version 1 Scope

Version 1 creates stable current sensors:

- Battery level
- Charging state
- Steps today
- Calories today
- Distance today
- Heart rate
- SpO2
- Stress
- Last successful update
- Connection state

Raw PPG and accelerometer data are not enabled by default. They may be added as disabled-by-default diagnostic sensors or a diagnostic service if the parser proves stable during testing. Continuous raw streaming is not part of the default behavior because it can increase battery drain and does not map cleanly to Home Assistant's normal sensor model.

## Deferred Scope

The following are deferred to Version 2 or later:

- Historical heart rate sync
- Historical SpO2 sync
- Historical stress sync
- Historical step details
- Sleep sync and sleep-stage parsing
- Long-running raw PPG or accelerometer recording
- Derived metrics such as HRV, sleep score, readiness, or activity classification
- Cloud, Health Connect, or phone-app-based data ingestion

## Architecture

The integration is organized as a HACS-compatible Home Assistant custom component:

```text
custom_components/fitorb/
  __init__.py
  binary_sensor.py
  bluetooth.py
  config_flow.py
  const.py
  coordinator.py
  manifest.json
  models.py
  sensor.py
  strings.json
  translations/en.json
  translations/de.json
```

`bluetooth.py` contains the low-level protocol constants, command builder, notification parser, and an async client wrapper around Home Assistant/Bleak connection helpers.

`coordinator.py` owns polling and state. It connects briefly, subscribes to notify characteristics, sends requests, waits for expected responses, updates a `FitorbData` model, and disconnects.

`sensor.py` maps numeric and timestamp fields from the latest `FitorbData` snapshot to Home Assistant `SensorEntity` entities.

`binary_sensor.py` maps boolean fields such as charging and BLE reachability to Home Assistant `BinarySensorEntity` entities.

`config_flow.py` supports Bluetooth discovery and manual setup by BLE address. The config entry stores the address, display name, and options such as polling interval.

## BLE Protocol Shape

The Colmi-compatible protocol uses 16-byte commands. A command is built from a short hex payload, padded with zeroes to 15 bytes, then finished with a one-byte checksum equal to the low byte of the sum of the first 15 bytes.

Known service and characteristic UUIDs:

- Command service: `6e40fff0-b5a3-f393-e0a9-e50e24dcca9e`
- Command write characteristic: `6e400002-b5a3-f393-e0a9-e50e24dcca9e`
- Command notify characteristic: `6e400003-b5a3-f393-e0a9-e50e24dcca9e`
- Firmware/raw service: `de5bf728-d711-4e47-af26-65e3012a5dc7`
- Firmware/raw write characteristic: `de5bf72a-d711-4e47-af26-65e3012a5dc7`
- Firmware/raw notify characteristic: `de5bf729-d711-4e47-af26-65e3012a5dc7`

Version 1 uses these command families:

- `03`: battery state
- `0a0200`: set metric units
- `43`: request activity data; Version 1 accepts the `0x73 0x12` day-summary notification and logs other activity packets for later analysis
- `6901`: request heart rate
- `6903`: request SpO2
- `6908`: request stress
- `39`: keepalive, if needed during longer reads

Notifications are parsed by the first byte and subtype:

- `0x03`: direct battery response
- `0x73 0x0c`: battery notification
- `0x73 0x12`: steps, calories, and distance summary
- `0x69 0x01`: heart rate request state/result
- `0x69 0x03`: SpO2 request state/result
- `0x69 0x08`: stress request state/result
- `0xa1 0x01`: raw SpO2 sensor data, diagnostic only
- `0xa1 0x02`: raw PPG sensor data, diagnostic only
- `0xa1 0x03`: raw accelerometer data, diagnostic only

The implementation must tolerate incomplete protocol knowledge. Unknown notifications are logged at debug level with their hex payload but do not fail the update.

## Data Flow

1. Home Assistant discovers the ring or the user enters its BLE address.
2. The config entry creates a coordinator and forwards setup to sensor platforms.
3. On each update interval, the coordinator resolves a connectable BLE device from Home Assistant's Bluetooth manager.
4. The coordinator opens a fresh BLE connection, subscribes to the command notify characteristic, and sends the configured request sequence.
5. Notifications are parsed into a `FitorbData` snapshot.
6. The coordinator marks the update successful, stores the timestamp, and notifies entities.
7. Entities expose values from the latest snapshot.
8. On timeout or connection failure, entities become unavailable while retaining the previous values in memory for recovery.

## Polling Strategy

Default polling should be conservative, starting around 5 minutes for battery and day summary. Heart rate, SpO2, and stress may take active measurements; they should be requested less aggressively or behind options if testing shows they wake LEDs or significantly affect battery life.

Suggested default:

- Battery and day summary: every 5 minutes
- Heart rate, SpO2, stress: every 15 minutes
- Connection timeout: 20 seconds
- Individual command response timeout: 10 seconds

Options can expose polling interval and whether active health measurements are enabled.

## Entity Model

All entities belong to one Home Assistant device with identifiers based on the integration domain and BLE address.

Sensor entity details:

- Battery level: percentage, battery device class, diagnostic category
- Charging state: binary sensor, battery charging device class, diagnostic category
- Steps today: total increasing state class; the midnight reset is expected and acceptable
- Calories today: kilocalories, total increasing state class; the midnight reset is expected and acceptable
- Distance today: meters, total increasing state class; the midnight reset is expected and acceptable
- Heart rate: beats per minute, measurement
- SpO2: percentage, measurement
- Stress: integer score, measurement
- Last successful update: timestamp device class, diagnostic category
- Connection state: binary sensor, diagnostic category

Unique IDs use the normalized BLE address plus a stable key, for example `aabbccddeeff_heart_rate`.

## Error Handling

Connection failures, timeouts, and parser errors are isolated to the current update. The coordinator sets availability false and logs a concise warning no more than once per failure type until recovery.

Unknown notification payloads are debug logs only. Malformed known payloads are ignored and counted in diagnostics.

If no connectable Bluetooth adapter is available, setup fails with a clear config flow error. Repair entities or issue registry entries are deferred.

## Diagnostics

The first implementation should include enough diagnostics to support protocol testing without exposing sensitive data:

- Integration version
- Configured address with optional redaction in diagnostics output
- Last update status
- Last successful update timestamp
- Last error type
- Count of unknown notifications
- Count of malformed notifications

Debug logs may include raw hex payloads when the user enables debug logging.

## Testing Strategy

Unit tests cover:

- 16-byte command construction and checksum
- Battery parser
- Step/calorie/distance parser
- Heart rate, SpO2, and stress notification parser
- Raw PPG and accelerometer parser if diagnostic parsing is included
- Coordinator behavior for successful update, timeout, and parser error paths

Home Assistant integration tests cover:

- Config flow from Bluetooth discovery
- Manual config flow by address
- Sensor setup from a config entry
- Entity values after coordinator data update
- Unload behavior

Manual validation covers:

- USB Bluetooth adapter passed through to the HA VM
- Ring discovered by HA Bluetooth
- Pairing or phone app disconnection behavior
- Successful sensor updates while the ring is worn
- Graceful failure while the ring is out of range or connected to the phone app

## HACS And Packaging

The repository should be shaped for HACS custom repository installation. It should include:

- `custom_components/fitorb/manifest.json`
- `README.md` with installation, Proxmox USB passthrough notes, and debug logging guidance
- `hacs.json`
- Basic tests and lint configuration

The manifest declares `bluetooth` as a dependency and uses `local_polling` as the IoT class because the integration initiates BLE reads on an interval.

## Open Risks

- The Fitorb model may differ from Colmi R02-R06 behavior in small protocol details.
- Some metrics may require enabling monitoring settings before data is produced.
- Heart rate, SpO2, and stress requests may return intermediate "running" states before final values.
- The ring may allow only one active BLE client at a time.
- Calories and distance units must be confirmed against real data.
- Sleep and historical packets are not fully specified and remain out of scope for Version 1.

## Acceptance Criteria

Version 1 is successful when:

- The integration can be installed as a custom Home Assistant integration.
- A Fitorb/Colmi-compatible ring can be configured through the UI.
- Home Assistant can connect to the ring using a passed-through USB Bluetooth adapter.
- The stable current sensors are created with unique IDs and correct device metadata.
- At least battery, charging state, steps, calories, distance, and one active health metric update successfully on real hardware.
- Connection failures do not crash Home Assistant or require reloading the integration.
- The design remains ready for a later historical sync extension without replacing the protocol layer.
