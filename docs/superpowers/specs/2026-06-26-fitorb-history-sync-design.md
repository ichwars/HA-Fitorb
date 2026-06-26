# Fitorb Smart Ring Historical Sync Design

## Goal

Add historical sync for Fitorb/Colmi-compatible smart rings after the current
sensor path has proven stable. Home Assistant should recover stored ring data
when the ring returns to Bluetooth range, so short or multi-day absences do not
lose all insight.

## Context

The current integration reads stable current values over direct BLE GATT. This
requires the ring to be in range of a Home Assistant Bluetooth adapter or a real
active BLE proxy. The phone app and Home Assistant mobile app cannot act as a
GATT relay for this integration.

The exact in-ring retention window is unknown. Public Colmi references show
history command families, but not a guaranteed cache duration. The design must
therefore discover what the ring actually returns and avoid assuming that a
given number of days is always present.

## Recommended Approach

Use a native BLE historical sync inside the existing `fitorb` integration.

The sync should be conservative and evidence-driven:

1. Read history directly from the ring over BLE.
2. Parse supported historical packet families into timestamped samples.
3. Store a small local sync ledger to deduplicate repeated reads.
4. Expose diagnostics showing last sync time and sample counts.
5. Only publish to Home Assistant long-term statistics after packet semantics are
   confirmed on real hardware.

This keeps the data local, avoids depending on QRing/Health Connect/cloud APIs,
and uses the protocol layer already working for live values.

## Alternatives Considered

### Phone Or QRing App Ingestion

This would use QRing, Health Connect, Google Fit, or phone-local data as the
source. It is not recommended because there is no documented QRing API, Health
Connect delivery to Home Assistant is unreliable for this use case, and mobile
app reverse engineering would be fragile.

### External Collector Daemon

A separate Linux/Python collector near the ring could read BLE and publish MQTT.
This may be useful later for homes where the HA Bluetooth adapter is far away,
but it adds another service to maintain. It is not the first implementation.

### Native Home Assistant BLE Sync

This is the recommended first path. It keeps the integration simple for the
current hardware setup and reuses the same connection handling as live sensors.

## Version 2 Scope

The first historical sync implementation should include:

- Config option for sync lookback window, defaulting to 7 days.
- Last history sync timestamp stored per config entry.
- Overlap window of at least 1 day to tolerate missed or partial syncs.
- Packet parsers for the best-known Colmi history families:
  - activity/day data
  - heart-rate history
  - sleep data if packet format is clear enough
  - stress/pressure history if packet format is clear enough
- Dedupe by metric, timestamp, and value.
- Diagnostic sensors:
  - last history sync
  - last history sync sample count
  - last history sync status
- Debug logging for unknown historical packets.

## Deferred Scope

These remain out of scope for the first history iteration:

- Cloud or QRing API integration.
- Phone acting as a BLE proxy.
- Permanent raw PPG or accelerometer recording.
- Derived scores such as readiness, recovery, or sleep score.
- Rewriting past Home Assistant state rows directly.

## Data Model

Introduce a history sample model separate from `FitorbData`:

```text
FitorbHistorySample
  metric: heart_rate | spo2 | stress | steps | calories | distance | sleep
  timestamp: timezone-aware datetime
  value: int | float | str
  source_day: date
  raw_hex: optional debug payload
```

Use an in-memory snapshot during each BLE read and a persistent store for the
sync ledger. The store does not need to retain every raw packet forever; it only
needs enough metadata to avoid duplicate publishing and to resume syncs.

## BLE Flow

The history sync runs after the live current-value poll succeeds and only when
the ring is connectable.

1. Connect to the ring and subscribe to notifications.
2. Read current battery/activity/health values as today.
3. If history sync is due, request history for each day in the lookback window.
4. Parse multi-packet responses until an end marker, expected count, or timeout.
5. Merge parsed samples into the dedupe ledger.
6. Update diagnostics and disconnect.

The sync should tolerate partial failures. If sleep parsing fails but heart-rate
history succeeds, the successful samples remain usable and the failure is logged
for that packet family.

## Home Assistant Publishing

Historical data should not be written by pretending old sensor states happened
now. The first implementation should publish diagnostics and keep parsed samples
available for validation.

After packet timestamps and units are confirmed, add Home Assistant statistics
publishing for numeric time-series where appropriate. That follow-up must use
Home Assistant-supported statistics APIs rather than direct recorder row edits.

Current sensors continue to show the latest known value. Historical sync is an
additional data path, not a replacement for current polling.

## Cache Retention Strategy

Because the ring's offline retention is unknown, the integration should default
to a 7-day lookback but make the value configurable. The sync should record what
the ring actually returns:

- requested day range
- days with any samples
- first and last sample timestamp
- packet families with no data
- packet families with malformed or unknown packets

This lets real hardware testing answer the practical question: how many days can
the ring hold while away from Home Assistant Bluetooth range?

## Error Handling

- Ring out of range: keep current behavior, mark connection unavailable, retry
  later.
- History packet timeout: keep live sensor update successful, mark history sync
  partial.
- Unknown history packet: log raw hex at debug level and count it.
- Duplicate sample: ignore without warning.
- Bad timestamp or impossible value: drop the sample and count it as malformed.

## Testing Strategy

Unit tests should cover:

- command construction for each history request
- parsing complete multi-packet history responses
- incomplete response timeout behavior
- dedupe behavior across overlapping sync windows
- coordinator behavior when history sync partially fails

Integration-style tests should cover:

- options for history sync lookback
- diagnostic sensors updating after a sync
- current sensors continuing to update when history sync is partial

Manual validation should include:

- leaving the ring away from HA Bluetooth for 1, 2, 3, and 7 days
- syncing after each absence
- comparing returned days and values with QRing where possible
- checking whether syncing with QRing first changes what HA can later read

## Acceptance Criteria

Version 2 history sync is ready when:

- Live sensors keep working as in Version 1.
- The integration can request and parse at least one historical packet family on
  real hardware.
- Repeated syncs do not duplicate samples.
- A missed Bluetooth window is recovered on a later poll when data still exists
  on the ring.
- Diagnostics show enough detail to measure the ring's real retention window.
- Unknown packet families are logged without breaking the sync.
