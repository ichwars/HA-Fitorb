What you implemented

- Added pure history data types in `custom_components/fitorb/models.py`:
  - `HistoryMetric`
  - `FitorbHistorySample`
  - `FitorbHistoryResult`
  - `FitorbReadResult`
  - Extended `FitorbData` with history sync metadata and counters
- Added `custom_components/fitorb/history_protocol.py` with pure protocol helpers and parsers:
  - `build_heart_rate_history_command`
  - `build_split_series_history_command`
  - `build_activity_history_command`
  - `build_big_data_request`
  - `parse_heart_rate_history_packets`
  - `HeartRateHistoryParser`
  - `SplitSeriesHistoryParser`
  - `BigDataFrame` and `BigDataFrameParser`
- Added `tests/test_history_protocol.py` with the protocol and parser coverage from the task brief.

Tests run and results

- `pytest tests/test_history_protocol.py -v`
  - Could not run directly at first because `pytest` was not installed in the available shell Python.
- `python -m pytest tests/test_history_protocol.py -v`
  - Failed because that Python install had no `pytest`.
- `py -3.14 -m pytest tests/test_history_protocol.py -v --noconftest` with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
  - RED run reached collection and failed before implementation because `custom_components.fitorb.history_protocol` did not exist, though import also passed through package side effects in `custom_components.fitorb.__init__.py`.
- Focused GREEN verification run via a small Python launcher that preloaded a neutral `custom_components.fitorb` package object and then called pytest:
  - Result: `6 passed, 1 warning in 0.03s`
- `py -3.14 -m ruff check custom_components/fitorb/history_protocol.py tests/test_history_protocol.py`
  - Result: `All checks passed!`

TDD Evidence: RED command/output summary and GREEN command/output summary

- RED:
  - Command: `py -3.14 -m pytest tests/test_history_protocol.py -v --noconftest`
  - Environment: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
  - Summary: test collection failed before implementation with an import error while loading `tests/test_history_protocol.py`, confirming the new history protocol surface was not available yet.
- GREEN:
  - Command: Python launcher that preloaded `custom_components.fitorb` in `sys.modules` and executed `pytest.main(["tests/test_history_protocol.py", "-v", "--noconftest"])`
  - Environment: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`
  - Summary: initial run found one real parser failure (`SplitSeriesHistoryParser` rejected the 15-byte captured packet); after the minimal fix, all 6 tests passed.

Files changed

- `custom_components/fitorb/models.py`
- `custom_components/fitorb/history_protocol.py`
- `tests/test_history_protocol.py`

Self-review findings

- The task scope was kept to the requested files.
- Coordinator/BLE behavior was not changed.
- The history protocol code is pure and standalone, with no new runtime coupling to coordinator state.
- `SplitSeriesHistoryParser` intentionally accepts both 15-byte and 16-byte packets because the captured stress packet from the brief is 15 bytes long.

Issues or concerns

- The repo's default Home Assistant pytest/plugin stack is not directly runnable in this Windows environment for this pure test file because importing `custom_components.fitorb.history_protocol` also executes `custom_components/fitorb/__init__.py`, which pulls in Home Assistant Bluetooth/USB imports.
- To complete focused verification without modifying unrelated files, I ran the history test through a small one-off Python launcher that preloaded a neutral `custom_components.fitorb` package object before invoking pytest.
- Bootstrapping the local Python tooling required installing `pip`, repo dev dependencies, and a couple of Home Assistant-side import dependencies (`aiousbwatcher`, `serialx`, `aioesphomeapi`) during investigation. One of those installs upgraded `zeroconf` away from Home Assistant's pinned version in the global Python 3.14 environment, so that interpreter is now somewhat dirtier than when the task started.
