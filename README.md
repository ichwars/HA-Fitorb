# Fitorb Smart Ring for Home Assistant

Custom Home Assistant integration for Fitorb smart rings that appear compatible with the Colmi R02-R06 BLE protocol.

## Scope

Version 1 exposes current values as Home Assistant entities:

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

Version 2 adds an experimental direct BLE history sync. It reads cached ring data
when the ring returns to Home Assistant Bluetooth range, deduplicates samples
locally, and exposes diagnostics so the real retention window can be measured on
your ring firmware.

## Bluetooth Requirements

Home Assistant must be able to make active BLE GATT connections to the ring. A Shelly Bluetooth proxy is not enough for this integration because Shelly devices forward advertisements but do not proxy active GATT connections.

For Home Assistant in Proxmox:

1. Plug a supported USB Bluetooth adapter into the Proxmox host.
2. Pass the USB device through to the Home Assistant VM.
3. Restart the VM.
4. In Home Assistant, add or verify the Bluetooth integration.
5. Disconnect the ring from the phone app before first setup if the ring only accepts one active BLE connection.

## Historical Sync

Historical sync uses the same direct Bluetooth path as the live sensors. The ring
must come back into range of the Home Assistant Bluetooth adapter or an active
GATT-capable proxy before cached samples can be recovered. The phone app and the
Home Assistant mobile app do not relay these BLE GATT reads.

The default lookback is 7 days with a 1 day overlap. The exact retention window is
firmware-dependent and not guaranteed by the public Colmi references. Use the
diagnostic sensors `Last history sync`, `History sample count`, `First history
sample`, and `Last history sample` to see what the ring actually returned.

The first history release stores and deduplicates parsed samples for validation.
It does not write old Home Assistant recorder state rows. Long-term statistics
publishing will be added after the packet timestamps and units are confirmed with
real hardware logs.

## Installation

Copy `custom_components/fitorb` into Home Assistant's `custom_components` directory or add `https://github.com/ichwars/HA-Fitorb` as a HACS custom repository.

Restart Home Assistant, then add **Fitorb Smart Ring** from **Settings > Devices & services**.

## Debug Logging

Add this to `configuration.yaml` when collecting logs:

```yaml
logger:
  logs:
    custom_components.fitorb: debug
```

Debug logs may include raw BLE notification payloads in hexadecimal form.
History debug logs may include raw historical BLE packets. These are useful when
checking whether QRing sync changes what Home Assistant can later read.

Heart rate, SpO2, and stress reads are best-effort. Some Fitorb/Colmi-compatible
firmware versions do not answer the known live health commands, so the integration
uses a short optional timeout until a measurement starts, then waits longer for
the final value while keeping battery/activity values. Until the first live health
value is observed, Home Assistant retries health reads on every summary poll.
Debug logging shows raw health packets when the ring answers without an immediate
value; the integration keeps waiting for a later live value in the same poll.

## Troubleshooting

### `org.bluez.Error.InProgress` or `Failed to connect after 12 attempt(s)`

BlueZ is still busy with a BLE connection attempt, or the ring is already connected
to another central device. Close the phone app, disconnect the ring from the phone
Bluetooth settings if needed, wait 30-60 seconds, and reload the integration. If the
error persists, restart the Home Assistant Bluetooth adapter or the HA VM.

When Home Assistant has no connectable Bluetooth path to the ring during a poll, the
integration keeps the last known values and marks the connection unavailable until a
later poll reaches the ring again.

## Known Limits

- The phone app may need to be disconnected while Home Assistant polls the ring.
- Heart rate, SpO2, and stress may stay unknown until the live health command
  format for this ring firmware is confirmed.
- Calories and distance units should be verified against real ring data.
- Unknown BLE packets are logged for analysis and ignored by Version 1.

## License

MIT
