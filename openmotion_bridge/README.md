# openmotion-bridge

The **single process that imports `omotion`** — and therefore the AGPL-3.0
boundary. It runs the Open-Motion science pipeline over synthetic / recorded
data (and, on a bench machine with the device attached, live scans), persists
the corrected record to a `ScanDatabase`, and serves it over plain HTTP/JSON.

Proprietary Neuratos services (the SvelteKit dashboard, ML jobs) talk to this
bridge **only over the network**, so AGPL never reaches closed code. Never
`import omotion` (or import this package) from a module you intend to keep
proprietary; keep this the only omotion-linking process.

## Run

```bash
pip install -e ".[dev,bridge]"
OPENMOTION_BRIDGE_DB=/tank/openmotion/scans.db python -m openmotion_bridge
# binds 127.0.0.1:5193 by default (OPENMOTION_BRIDGE_HOST / _PORT to override).
# NB: 5192 is already used on Niflheim by the Sana/SD image-gen service.
```

## API

| Method | Path | What |
|---|---|---|
| GET  | `/health` | service + db + fixture/device status |
| GET  | `/scans` | scan index (ScanDatabase `sessions`) |
| GET  | `/scan/{id}?side&cam_id&limit` | corrected per-frame timeseries for one session |
| POST | `/replay` | run a synthetic or CSV replay through the real pipeline → ScanDatabase + live ring |
| GET  | `/live/{subject_id}` | latest per-side BFI/BVI from the most recent replay |

`POST /replay` body (synthetic):

```json
{"mode": "synthetic", "scan_id": "s1", "subject_id": "subjA",
 "n_frames": 200, "dark_interval": 40,
 "left_camera_mask": 1, "right_camera_mask": 0}
```

CSV replay: `{"mode": "csv", "scan_id": "...", "subject_id": "...",
"raw_csv_left": "/path/scan_..._left_maskFF.csv", "raw_csv_right": null}` — e.g.
the committed `tests/fixtures/scan_owC18EHALL_*_{left,right}_maskFF.csv`.

## Notes / follow-ups

- **SQLite concurrency (P2):** when the dashboard reads the same `.db` while a
  live scan writes it, enable WAL + a single-writer discipline first.
- **RTDB live push (P2):** a `NetworkSink` posting the `live`/`final` channels
  to the backbone RTDB `/openmotion/*` namespace lands the real-time dashboard;
  not wired here yet (keeps the bridge runnable standalone).
- Calibration for replay is identity-ish (BFI/BVI are relative indices); a live
  bench scan loads real calibration from the console EEPROM.
