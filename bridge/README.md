# Bridge - Barcode and Weighing Integration

This Windows bridge receives serial-derived barcode and weight data from a USR-TCP232-302 gateway, captures raw frames, parses only when a verified protocol is configured, queues valid readings in SQLite and posts them to the existing ERP API. It does not duplicate ERP validation, tare calculation, deduplication, production-record creation or stock posting.

## Files

- `main.py` - runtime loop, health transitions, status display, queue drain and bounded reconnect handling.
- `config.py` - validated settings loaded from `bridge/.env` and repository `.env`.
- `device_client.py` - TCP client mode for USR TCP Server, optional TCP server mode and local simulation.
- `parser.py` - byte-stream framing plus raw/regex/simulation parsers.
- `erp_client.py` - JWT or username/password login and ERP API calls.
- `queue_store.py` - durable SQLite queue with attempts, retry time and dead letters.
- `logging_setup.py` - structured JSON logs, rotating local files and optional GCS upload.
- `check_connection.ps1` - Windows preflight for IP, MAC, TCP port and GCS config.
- `requirements.txt` - Python dependencies.
- `.env.example` - configuration template with placeholders, not live credentials.
- `run_bridge.ps1` - Windows virtualenv setup and startup script.

## Install and start

From `bridge/`:

```powershell
.\run_bridge.ps1
```

Manual equivalent:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\check_connection.ps1
.\.venv\Scripts\python.exe main.py
```

`run_bridge.ps1` creates `.env` from `.env.example` only when `.env` is absent. Keep `.env` local and uncommitted. The template deliberately leaves `DEVICE_PORT` empty; the bridge fails fast until the verified USR Local Port Number is entered.

## USR-TCP232-302 binding check

Confirmed topology:

- Manufacturer/model: USR-IOT `USR-TCP232-302`, type `C7`.
- Power input: `DC 5–7V`.
- Default IP: `192.168.0.7`.
- Label MAC: `D4:AD:20:DB:E8:C9`.
- Factory login shown on label: `admin / admin`; change it if still active.
- USR gateway mode: `TCP Server`.
- Bridge mode: `DEVICE_MODE=tcp_client`.
- Bridge target: `DEVICE_HOST=192.168.0.7`.
- Bridge port: `DEVICE_PORT=<USR TCP Server Local Port Number>`.
- `9000` is only a placeholder and is not used as a default.
- `232` in the model name refers to the serial interface, not a TCP port.
- `DEVICE_BIND_HOST` and `DEVICE_BIND_PORT` are unused in this topology.

The PC network adapter must be on the same subnet, for example `192.168.0.x` with a compatible mask, and must not use `192.168.0.7`. Reserve `192.168.0.7` for MAC `D4:AD:20:DB:E8:C9` in DHCP or set it statically in the USR utility.

Run the preflight from `bridge/`:

```powershell
.\check_connection.ps1
```

It prints adapter addresses, PING, ARP/MAC match, exact TCP port result and GCS target/credential status. It reads `.env` and does not print secrets.

Manual equivalent after reading the port from the USR utility:

```powershell
ping 192.168.0.7
arp -a | findstr 192.168.0.7
Test-NetConnection -ComputerName 192.168.0.7 -Port <VERIFIED_LOCAL_PORT>
```

`TcpTestSucceeded : True` means the bridge PC can reach the listener. An open port is not automatically the serial data port; the USR Local Port Number is authoritative.

Serial values are intentionally blank in `.env.example`. Fill `DEVICE_BAUDRATE`, `DEVICE_BYTESIZE`, `DEVICE_PARITY`, `DEVICE_STOPBITS`, `DEVICE_TIMEOUT_SECONDS` and `DEVICE_FRAME_DELIMITERS` only after matching the indicator and USR settings. With no delimiter configured, the bridge treats each TCP read chunk as a bounded raw frame instead of guessing CR/LF.

## Required `.env` values

Minimum live-mode values:

```ini
ERP_BASE_URL=https://kalika-erp-h7zrl6txua-el.a.run.app
ERP_TOKEN=<least-privilege JWT>
DEVICE_MODE=tcp_client
DEVICE_ID=USR-TCP232-302
DEVICE_MAC=D4:AD:20:DB:E8:C9
DEVICE_HOST=192.168.0.7
DEVICE_PORT=<USR TCP Server Local Port Number>
PARSER_MODE=raw
DRY_RUN=true
QUEUE_DB_PATH=bridge/data/queue.sqlite3
LOG_DIR=kalisoftai-datahub/Kalika_inventory/Logs
GCS_BUCKET=kalisoftai-datahub
GCS_LOG_PREFIX=Kalika_inventory/Logs
GOOGLE_APPLICATION_CREDENTIALS=<path to service account JSON>
```

Use `ERP_USERNAME` and `ERP_PASSWORD` instead of `ERP_TOKEN` only if a dedicated ERP service account is approved. Do not commit credentials. Never log tokens, passwords, headers or full environment dumps.

## ERP data contract

The bridge posts to `POST /production/machine/transactions`. The ERP schema requires:

- `size`
- `box_number`
- `gross_weight`

Optional fields the bridge can pass when the frame provides them:

- `product_id`, `product`, `item_code`
- `grade`, `micron`, `production_date`
- `barcode`
- `remark`
- `transaction_id`
- `machine_id`

Product details must come from the confirmed machine message or ERP product master. The bridge does not invent product, batch, lot, tare or net values. Weights are parsed as `Decimal` and sent as finite positive decimal strings.

Example regex mapping only after a real frame is available:

```ini
PARSER_MODE=regex
FRAME_REGEX=^(?P<status>ST)[,;](?P<bc>[^,;]+)[,;](?P<sz>[^,;]+)[,;](?P<bx>[^,;]+)[,;](?P<wt>[0-9.]+)
FIELD_MAP={"bc":"barcode","sz":"size","bx":"box_number","wt":"gross_weight"}
STABLE_FIELD=status
STABLE_VALUES=ST
REQUIRE_BARCODE=true
```

If the actual BS44 format is unknown, leave `PARSER_MODE=raw`. Raw frames are logged, no mapping is attempted and nothing is submitted to ERP.

## Simulation

For local development without hardware:

```ini
DEVICE_MODE=simulation
PARSER_MODE=simulation
DRY_RUN=true
```

Simulation frames are JSON and include sample product, size, box, barcode and weight values. Keep `DRY_RUN=true` until live posting is approved.

## Device health

The bridge reports one health status at a time through heartbeats and `/production/machine/status`:

- `CONFIG_ERROR` - required configuration invalid or missing.
- `DISCONNECTED` - no active TCP connection.
- `CONNECTING` - connection attempt in progress.
- `CONNECTED_NO_DATA` - TCP connected but no bytes received yet.
- `RECEIVING_UNPARSED` - bytes arrive but no valid reading parsed.
- `CONNECTED_STALE` - last reading is older than `DEVICE_STALE_AFTER_SECONDS`.
- `UNSTABLE` - latest reading is not stable, if the protocol exposes that flag.
- `STABLE` - fresh valid stable reading available.
- `DEVICE_ERROR` - socket or protocol error/overload.

`last_byte_at` and `last_valid_reading_at` are tracked separately. A live TCP socket with no valid scale data is not reported as a healthy weighing device. The UI page `/machine-bridge` shows device health, gateway IP/port, MAC, parser mode, dry-run flag, latest reading, reading age, raw frames, parse errors, diagnostics and the transaction inbox. It polls every 2 seconds and does not modify production records.

## Polling diagnostics and error breakdown

The bridge emits `device.poll.summary` every `DIAGNOSTICS_POLL_INTERVAL_SECONDS` (default `2`) with device health, byte count, frame counts, reading counts, queue counts, error counts, last timestamps and the current error message. Every classified failure also emits `device.poll.error` with a category: `device`, `frame`, `parse`, `stale`, `erp`, `erp_frame`, `erp_heartbeat` or `erp_status`.

The same breakdown is attached to heartbeats and returned by `GET /production/machine/status`:

- `diagnostics` - last bridge-generated poll snapshot.
- `error_breakdown.bridge` - categorized bridge error counts.
- `error_breakdown.frames` - grouped raw-frame error messages from ERP storage.
- `error_breakdown.transactions` - grouped failed transaction error messages from ERP storage.
- `recent_errors` - latest frame and transaction errors for quick triage.

The `/machine-bridge` UI shows these counters, grouped messages and recent errors so unresolved issues can be identified without reading raw JSON logs. Lower `DIAGNOSTICS_POLL_INTERVAL_SECONDS` for faster troubleshooting; raise it to reduce log volume.

## API telemetry and UI

Raw frames and bridge heartbeats are posted to ERP before any parsed transaction is submitted:

- `POST /production/machine/frames`
- `GET /production/machine/frames`
- `POST /production/machine/heartbeat`
- `GET /production/machine/status`

Telemetry is non-blocking: API failures are logged locally/GCS and never stop machine reading. `ERP_TELEMETRY_ENABLED=false` disables telemetry. `ERP_FRAME_REPORT_MODE` controls what is sent: `all`, `parsed`, `errors` or `none`. In `PARSER_MODE=raw`, frames are stored with parser status `RAW` and no transaction is submitted.

## Queue and retry

Each valid reading is stored once in `bridge/data/queue.sqlite3`. The transaction key is the parsed `transaction_id`, or a SHA-256 prefix of the raw frame when no ID is present. Retries reuse that same key so ERP deduplication remains authoritative.

`MAX_ATTEMPTS` and `RETRY_BASE_DELAY_SECONDS` control queue retry backoff. TCP reconnect uses `DEVICE_RECONNECT_MIN_SECONDS`, `DEVICE_RECONNECT_MAX_SECONDS` and bounded jitter. Failed queue attempts that exceed the limit are kept as `DEAD` rows for review.

## Logs

Structured JSON logs are written to `LOG_DIR/LOG_FILE_NAME` with rotation. Every event carries UTC timestamp, level, component, event, device ID, host, port, connection ID, sequence and correlation ID. Required diagnostic events include:

- `device.config.loaded`, `device.config.invalid`
- `device.connect.started`, `device.connect.succeeded`, `device.connect.failed`
- `device.connection.closed`, `device.reconnect.scheduled`
- `device.bytes.received`, `device.frame.completed`, `device.frame.invalid`
- `device.parse.succeeded`, `device.parse.failed`
- `device.reading.stale`, `device.reading.captured`, `device.reading.rejected`
- `device.worker.started`, `device.worker.stopped`, `device.health.changed`
- `device.poll.summary`, `device.poll.error`
- `erp.request`, `erp.response`, `erp.status`, `erp.status.error`
- `queue.enqueued`, `queue.sent`, `queue.retry`, `queue.dead`
- `gcs.upload.success`, `gcs.upload.error`

Raw text/hex previews are off by default. Enable them only with `WEIGHING_RAW_LOG_ENABLED=true` and cap each preview with `WEIGHING_RAW_LOG_MAX_BYTES` (default `64`). Logging failures are suppressed so they cannot stop machine reading.

GCS upload runs on a background daemon thread. Enable it with:

```ini
GCS_UPLOAD_ENABLED=true
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
WEIGHING_ENVIRONMENT=local
DEVICE_ID=USR-TCP232-302
```

Dated objects are written under:

```text
gs://kalisoftai-datahub/Kalika_inventory/Logs/weighing/<environment>/<device-id>/YYYY/MM/DD/<filename>.jsonl
```

The service account needs `roles/storage.objectAdmin` on bucket `kalisoftai-datahub`. Do not add a new bucket or credentials without checking the project's existing GCS configuration.

## Remaining hardware configuration

Before live operation, confirm:

- Actual USR TCP Server Local Port Number.
- USR model and firmware.
- PC IP address and subnet on the same network as `192.168.0.7`.
- IP reservation or static binding for MAC `D4:AD:20:DB:E8:C9` to `192.168.0.7`.
- BS44 baud rate, data bits, parity, stop bits, flow control and delimiter.
- Actual BS44 message format, including stable/unstable marker, barcode, weight, size and box fields.
- Whether barcode is mandatory for every accepted reading.
- ERP service identity and least-privilege token or credentials.
- GCS upload service account with `roles/storage.objectAdmin` on the log bucket.

No tests, migrations or live ERP transactions were run as part of this implementation.
