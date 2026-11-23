# Kalika ERP Dashboard, API Data, User Class and Durable Log Map

## 1. Scope and current branch

This document describes the application state on `feat/hardware-rs232-api` after the 2-second weighing-bridge polling diagnostics work. It is documentation-only for the running app: no deploy was performed while producing this file.

Baseline commit before this documentation/logging update: `518fc12 feat(bridge): add polling diagnostics and error breakdown`.

The dashboard reads live ERP data through FastAPI APIs. Those APIs are also the boundary where user class, data medium and action intent can be classified consistently for monitoring, audit and log storage.

## 2. Custom taxonomy: medium, intent, classes

| Term | Meaning used here | Values used in this document |
|---|---|---|
| `medium` | Channel or storage surface that carries the data | `UI_DASH`, `UI_FORM`, `HTTP_API`, `TCP_BRIDGE`, `GCS_ASSET`, `GCS_IMPORT`, `DB_AUDIT`, `DB_CALC`, `ALERT_ENGINE`, `MAIL`, `FILE_EXPORT`, `PRINTER` |
| `intent` | Why the data is being read or written | `MONITOR`, `READ`, `MAINTAIN`, `PLAN`, `EXECUTE`, `RECONCILE`, `INTEGRATE`, `DIAGNOSE`, `AUTHORIZE`, `RESPOND`, `EXPORT`, `AUDIT`, `REMOVE` |
| `classes` | User or service access class allowed to use the data | `admin`, `manager`, `store`, `production`, `dispatch`, `viewer`, `bridge-service` |

Application roles are defined in `backend/app/models.py` as `admin`, `manager`, `store`, `production`, `dispatch`, `viewer`. `bridge-service` is not a UI role; it is the logical class for the weighing bridge calling `/production/machine/*` with a dedicated token.

```text
                         +-------------------+
                         |   USER / SERVICE  |
                         | admin manager ... |
                         +---------+---------+
                                   |
             medium                |                intent
      UI_DASH | UI_FORM | TCP_BRIDGE | GCS | DB       MONITOR | EXECUTE | DIAGNOSE
                                   |
                                   v
                         +-------------------+
                         |   FASTAPI BOUNDARY|
                         | auth + audit + log|
                         +---------+---------+
                                   |
                         +---------+---------+
                         | POSTGRES / GCS /  |
                         | JSONL / DB AUDIT  |
                         +-------------------+
```

## 3. Dashboard data flow

```text
  Browser / Dashboard.jsx
        |
        |  GET /dashboard/summary
        |  GET /dashboard/dispatch-by-plant
        |  GET /dashboard/production-by-product
        |  GET /dashboard/order-pipeline
        |  GET /dashboard/inventory-status
        |  GET /dashboard/daily-trends
        |  GET /dashboard/low-stock-list
        |  GET /alerts/count
        |  GET /material-requirements/rm-shortage
        v
  FastAPI CurrentUser -> PostgreSQL -> JSON response
        |
        +--> durable JSONL log (http.request, medium, intent, user class)
        +--> console/Cloud Run log
        +--> GCS log object (periodic upload)
```

The frontend loader is `frontend/src/pages/Dashboard.jsx:62-87`. The dashboard API is read-only in `backend/app/routers/dashboard.py`; all dashboard endpoints currently use `CurrentUser`.

## 4. Dashboard API contracts

### `/dashboard/summary`

Response keys from `backend/app/routers/dashboard.py:73-87`:

| Group | Fields | Meaning |
|---|---|---|
| Date / orders | `report_date`, `total_orders`, `new_orders_today`, `pending_orders`, `completed_orders`, `orders_in_production`, `ready_to_dispatch`, `orders_dispatched`, `order_value` | Order pipeline health and value. `pending_orders` = `new + confirmed`. |
| Raw materials | `raw_material_count`, `raw_material_stock`, `raw_material_balance`, `low_stock_items`, `out_of_stock_items` | RM master and stock risk. `low_stock_items` = `0 < current_stock < min_level`; `out_of_stock_items` = `current_stock <= 0`. |
| Production | `production_planned_qty`, `production_produced_qty`, `production_pending_qty` | Planned vs produced vs pending quantity. |
| Purchase | `purchase_count`, `purchase_value` | Purchase order count and value. |
| Dispatch | `dispatch_scheduled`, `dispatch_done`, `dispatch_pending` | Dispatch schedule de-duplicated per sales-order line. |
| Masters | `supplier_count`, `customer_count`, `plant_count`, `product_count`, `store_items` | Master data and store item counts. |

### Related dashboard data APIs

| Endpoint | Data returned | Medium | Intent | Classes |
|---|---|---|---|---|
| `GET /dashboard/dispatch-by-plant` | Dispatch quantity grouped by plant | `UI_DASH` | `MONITOR` | all authenticated users |
| `GET /dashboard/production-by-product` | Produced quantity grouped by product | `UI_DASH` | `MONITOR` | all authenticated users |
| `GET /dashboard/order-pipeline` | Order counts by pipeline stage | `UI_DASH` | `MONITOR` | all authenticated users |
| `GET /dashboard/inventory-status` | Stock status by inventory item | `UI_DASH` | `MONITOR` | all authenticated users |
| `GET /dashboard/daily-trends` | Last 30 distinct dates from `DispatchLine` and `ProductionMovement` | `UI_DASH` | `MONITOR` | all authenticated users |
| `GET /dashboard/low-stock-list` | Items below minimum level | `UI_DASH` | `MONITOR` | all authenticated users |
| `GET /alerts/count` | `unread`, `total_open`, `critical_unread` | `ALERT_ENGINE` | `RESPOND` | all authenticated users |
| `GET /material-requirements/rm-shortage` | Raw material shortage rows with positive shortage | `DB_CALC` | `PLAN` | manager, store, production, admin |
| `GET /meta/statuses` | Status vocabularies for filters and forms | `DB_CALC` | `READ` | all authenticated users |
| `GET /meta/filters` | Customer, plant and product filter options | `DB_CALC` | `READ` | all authenticated users |
| `GET /dispatch/summary` | Per-customer dispatch totals and completion metrics | `UI_DASH` | `MONITOR` | dispatch, manager, admin |

## 5. API data map by domain

This table covers the API prefixes registered in `backend/app/main.py:531-566` and the data each domain owns.

| API prefix | Data from / to API | Medium | Primary intent | Intended classes |
|---|---|---|---|---|
| `/auth` | Login/logout, JWT, password change, auth audit | `HTTP_API`, `DB_AUDIT` | `AUTHORIZE` | all users |
| `/users` | User master, role changes, user audit | `UI_FORM`, `DB_AUDIT` | `MAINTAIN`, `AUTHORIZE` | admin |
| `/meta` | Dropdown statuses and filters | `DB_CALC` | `READ` | all users |
| `/customers`, `/suppliers`, `/products`, `/plants`, `/salespersons` | Business master data | `UI_FORM` | `MAINTAIN` | admin, manager, relevant staff |
| `/raw-materials` | RM master, balances, stock, imports | `UI_FORM`, `GCS_IMPORT` | `MAINTAIN`, `RECONCILE` | store, manager, admin |
| `/purchases` | Purchase orders, receipts, PRN linkage | `UI_FORM` | `PLAN`, `RECONCILE` | store, manager, admin |
| `/inventory` | Inventory rows, movements, low stock, adjustments | `UI_FORM` | `EXECUTE`, `RECONCILE` | store, production, dispatch, admin |
| `/inventory/locations`, `/inventory/transfers`, `/inventory/dispatches` | Internal locations, stock transfers, customer dispatch stock | `UI_FORM` | `EXECUTE` | store, dispatch, admin |
| `/production` | Production orders, actuals, plan-vs-actual, completions, movements, imports | `UI_FORM` | `PLAN`, `EXECUTE` | production, manager, admin |
| `/production` machine and weighing APIs | Tare settings, machine status, heartbeat, raw frames, scans, transactions, simulation, records, retry-sync | `TCP_BRIDGE`, `HTTP_API` | `INTEGRATE`, `DIAGNOSE`, `RECONCILE` | bridge-service, store, production, admin |
| `/orders` | Sales orders, pending orders, status changes, import, email | `UI_FORM`, `MAIL` | `PLAN`, `EXECUTE` | manager, dispatch, admin |
| `/local-orders` | Local order master, plans, imports, reports | `UI_FORM`, `GCS_IMPORT` | `PLAN`, `MAINTAIN` | manager, production, admin |
| `/dispatch` | Dispatch summary, dispatch lines, customer items, order lines, completion | `UI_FORM` | `EXECUTE`, `MONITOR` | dispatch, manager, admin |
| `/plans` | Production/dispatch plans | `UI_FORM` | `PLAN` | manager, production, admin |
| `/dashboard` | KPI cards and dashboard charts | `UI_DASH` | `MONITOR` | all users |
| `/kaliflow` | GCS-backed HTML, video, logo and toggle state | `GCS_ASSET` | `MONITOR` | all users; toggle admin |
| `/api/v1/sales-ops/prompts` | Read-only sales prompt catalog with `intent` fields | `HTTP_API` | `READ` | sales, manager, admin |
| `/reports` | CSV/Excel/PDF exports, delivery logs, stamp/debug assets | `FILE_EXPORT`, `GCS_ASSET` | `EXPORT` | manager, admin, authorized staff |
| `/requirements` | Requirement status/category overlay | `DB_CALC` | `PLAN`, `RESPOND` | manager, production, store |
| `/salespersons` | Salesperson master | `UI_FORM` | `MAINTAIN` | manager, admin |
| `/material-requirements` | BOM-driven shortage and production readiness summaries | `DB_CALC` | `PLAN` | manager, production, store |
| `/fulfilment` | Per-order-line statuses: `FULFILLED`, `OVER_FULFILLED`, `READY_FOR_DISPATCH`, `PRODUCTION_REQUIRED`, `PURCHASE_REQUIRED`, `MANUAL_DECISION_REQUIRED` | `DB_CALC` | `RECONCILE` | manager, production, store, dispatch |
| `/bom` | BOM groups, items, validation | `UI_FORM` | `MAINTAIN` | production, manager, admin |
| `/alerts` | Alert list/count, create/update/resolve | `ALERT_ENGINE` | `RESPOND` | all users; mutations authorized staff |
| `/packaging-lists` | Packaging list master and duplicates | `UI_FORM` | `EXECUTE` | production, store, admin |
| `/employees` | Employee master, sensitive HR field masking/unmasking, PDF/export/import | `UI_FORM`, `FILE_EXPORT` | `MAINTAIN` | admin, manager; explicit unmask checks |
| `/prn` | PRN constants, workflow, attachments, PDF workflow | `UI_FORM`, `PRINTER` | `EXECUTE` | store, production, admin |
| `/activity-log` | Audit-log options, summary, list and export | `DB_AUDIT`, `FILE_EXPORT` | `AUDIT`, `EXPORT` | admin, manager |
| `/health` | Database health and service version | `HTTP_API` | `MONITOR` | public/ops |
| SPA root and catch-all | Frontend HTML and static assets | `HTTP_API` | `READ` | all users |

## 6. Machine and weighing diagnostics data

The bridge posts telemetry before parsed transactions. ERP isolates raw capture from business posting.

```text
  USR-TCP232-302 (TCP Server)
          |
          | device bytes
          v
  bridge/main.py
    frame buffer -> parser -> SQLite queue -> ERP API
          |            |          |             |
          |            |          |             +-> /production/machine/transactions
          |            |          +-> retry/DEAD queue rows
          |            +-> device.poll.summary / device.poll.error
          +-> raw frame event -> /production/machine/frames

  ERP service: validate -> dedupe -> tare -> net weight
             -> ProductionRecord -> stock movement (net only)
```

`GET /production/machine/status` returns:

| Field group | Data |
|---|---|
| `connection` | connection type/status, host, port, last error, last seen |
| `device_health` | one of `CONFIG_ERROR`, `DISCONNECTED`, `CONNECTING`, `CONNECTED_NO_DATA`, `RECEIVING_UNPARSED`, `CONNECTED_STALE`, `UNSTABLE`, `STABLE`, `DEVICE_ERROR` |
| `health_statuses` | complete list of bridge health states |
| `diagnostics` | `poll_interval_seconds`, `generated_at`, frame counts, reading counts, queue counts, last error |
| `error_breakdown` | `bridge` categories, grouped raw-frame errors, grouped failed transaction errors |
| `recent_errors` | latest frame and transaction errors with source, message and timestamp |
| `counters` | received today, processed, duplicates, failed and other weighing counters |
| `frames` / `last_frame` | raw text/hex previews and parse status |
| `last_transaction`, `last_record` | latest inbox and production-record state |

Bridge log categories currently stored in `error_breakdown.bridge`: `device`, `frame`, `parse`, `stale`, `erp`, `erp_frame`, `erp_heartbeat`, `erp_status`, `diagnostics`.

## 7. User class matrix

```text
  admin       [ALL] users, RBAC, audit, reports, Kaliflow toggle, machine config
  manager     [WIDE] dashboards, orders, production, inventory, dispatch, reports, alerts
  store       [STOCK] raw materials, inventory, purchases, tare, weighing records
  production  [MAKE] production orders, BOM, packaging lists, machine status
  dispatch    [SHIP] dispatch, order lines, stock availability
  viewer      [READ] dashboards and read-only status pages
  bridge-svc  [IOT ] /production/machine/frames|heartbeat|status only
```

| Class | Can monitor | Can operate | Can authorize/administer | Log identity |
|---|---|---|---|---|
| `admin` | all dashboards, audit, alerts | all business modules | user/role changes, Kaliflow toggle | user id + role `admin` |
| `manager` | dashboards, reports, shortages, fulfilment | orders, production, dispatch, inventory | no intended user management | user id + role `manager` |
| `store` | inventory, low stock, purchases, weighing status | stock, RM, tare, machine transactions | no intended user management | user id + role `store` |
| `production` | production KPIs, machine status, BOM readiness | orders, actuals, packaging lists | no intended user management | user id + role `production` |
| `dispatch` | dispatch KPIs, order pipeline | dispatch lines, customer dispatch | no intended user management | user id + role `dispatch` |
| `viewer` | dashboards and read-only pages | no intended mutations | no | user id + role `viewer` |
| `bridge-service` | device health and queue counters | telemetry/frame/transaction posting | no UI access | dedicated token; no UI role |

Security note: `backend/app/auth.py:62-70` currently lets any authenticated user through `AdminUser`, `ManagerOrAdmin` and `AllStaff` because `admin` is present in their allowed sets. UI hiding in `frontend/src/components/Layout.jsx` is not server-side authorization. Some handlers add explicit in-body checks, but this dependency should be fixed before relying on the intended matrix above.

## 8. Durable log storage

"All logs will be stored" is implemented as layered storage. Application and API logs are written as JSONL locally and uploaded to GCS. Business events are additionally stored in dedicated database tables for audit and reconciliation.

| Layer | Stored data | Location | Notes |
|---|---|---|---|
| Backend console | uvicorn + application logs | Cloud Run stdout | Searchable in Cloud Logging. |
| Backend JSONL | every `http.request`, `http.request.failed`, startup/shutdown, service warnings/errors | `LOG_DIR/LOG_FILE_NAME`, default `data/logs/kalika-erp.jsonl` | Rotating file, default 10 MiB x 10 backups. |
| Backend GCS upload | copies of the rotating backend JSONL files | `gs://kalisoftai-datahub/Kalika_inventory/Logs/api/<APP_ENV>/YYYY/MM/DD/kalika-erp.jsonl` | Enabled by default; interval 60s; requires `roles/storage.objectAdmin`. |
| Bridge JSONL | structured weighing events, poll summaries, errors, GCS upload events | bridge `LOG_DIR/bridge.jsonl` | Rotating JSONL, structured fields. |
| Bridge GCS upload | weighing log files | `gs://kalisoftai-datahub/Kalika_inventory/Logs/weighing/<environment>/<device-id>/YYYY/MM/DD/bridge.jsonl` | Enabled from bridge config; raw previews capped/disabled by default. |
| DB audit | user and business mutations | `audit_logs` table | Exposed through `/activity-log`. Immutable via before-update guard. |
| Weighing inbox | raw frames, failed/duplicate transactions, production records | `machine_raw_frames`, `weighing_transactions`, `production_records` | ERP-side durable audit of weighing data. |
| Machine diagnostics | heartbeat health, config JSON, error/count breakdown | `machine_connections.config` | Latest state for UI status page. |
| Bridge queue | pending, sent, dead-letter events with attempts and last error | bridge SQLite `queue_events` | `DEAD` rows retained for review. |

```text
  gs://kalisoftai-datahub/Kalika_inventory/Logs/
  |
  +-- api/
  |   `-- production/
  |       `-- YYYY/MM/DD/
  |           `-- kalika-erp.jsonl
  |
  `-- weighing/
      `-- <environment>/
          `-- <device-id>/
              `-- YYYY/MM/DD/
                  `-- bridge.jsonl

  local container
  +-- /app/data/logs/kalika-erp.jsonl
  +-- /app/data/logs/kalika-erp.jsonl.1 ... .10
  +-- /app/data/<bridge queue sqlite>
  `-- reports/
```

### Backend log record fields

The backend JSON formatter stores timestamp, level, logger, component, event, message, module, function, line, and optional request fields:

```text
{
  "timestamp": "...Z",
  "level": "INFO",
  "logger": "kalika",
  "component": "http",
  "event": "http.request",
  "message": "http.request",
  "request_id": "12hexchars",
  "http_method": "GET",
  "http_path": "/dashboard/summary",
  "http_status": 200,
  "duration_ms": 18.42,
  "user_id": 7,
  "user_role": "manager",
  "medium": "HTTP_API",
  "intent": "MONITOR",
  "user_class": "manager"
}
```

Request logging does not write headers, cookies, request bodies, JWTs, DB passwords or mail passwords. Failed requests are logged as `http.request.failed` with exception text and stack trace.

### Environment controls

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `production` | GCS log folder segment. |
| `LOG_DIR` | `data/logs` | Local rotating JSONL directory. |
| `LOG_FILE_NAME` | `kalika-erp.jsonl` | Backend log file name. |
| `LOG_LEVEL` | `INFO` | Root and uvicorn log level. |
| `LOG_MAX_BYTES` | `10485760` | Rotate size. |
| `LOG_BACKUP_COUNT` | `10` | Rotated files kept locally. |
| `GCS_LOG_UPLOAD_ENABLED` | `true` | Enables backend JSONL upload. |
| `GCS_LOG_PREFIX` | `Kalika_inventory/Logs` | GCS prefix root. |
| `GCS_LOG_UPLOAD_INTERVAL_SECONDS` | `60` | Upload loop interval. |
| `GOOGLE_APPLICATION_CREDENTIALS` | unset | Optional explicit service-account JSON path. |

`deploy.sh` sets `APP_ENV`, `LOG_DIR`, `LOG_FILE_NAME`, `LOG_LEVEL`, `GCS_LOG_UPLOAD_ENABLED`, `GCS_LOG_PREFIX` and `GCS_LOG_UPLOAD_INTERVAL_SECONDS` for Cloud Run, and grants the runtime service account `roles/storage.objectAdmin` for log uploads. No deployment was executed for this documentation change.

## 9. Log event catalogue

| Event | Source | Medium | Intent | Stored where |
|---|---|---|---|---|
| `http.request`, `http.request.failed` | backend middleware | `HTTP_API` | depends on path/method | console, JSONL, GCS |
| `gcs.uploader.started`, `gcs.uploader.disabled`, `gcs.uploader.error` | backend uploader | `GCS_ASSET` | `DIAGNOSE` | console, JSONL, GCS |
| `gcs.upload.success`, `gcs.upload.error` | backend and bridge uploader | `GCS_ASSET` | `DIAGNOSE` | console, JSONL, GCS |
| `device.poll.summary`, `device.poll.error` | weighing bridge | `TCP_BRIDGE` | `DIAGNOSE` | bridge JSONL, GCS, heartbeat diagnostics |
| `device.config.loaded`, `device.config.invalid` | weighing bridge | `TCP_BRIDGE` | `DIAGNOSE` | bridge JSONL, GCS |
| `device.connect.*`, `device.connection.closed`, `device.reconnect.scheduled` | weighing bridge | `TCP_BRIDGE` | `INTEGRATE` | bridge JSONL, GCS |
| `device.bytes.received`, `device.frame.completed`, `device.frame.invalid` | weighing bridge | `TCP_BRIDGE` | `INTEGRATE` | bridge JSONL, GCS |
| `device.parse.succeeded`, `device.parse.failed`, `device.reading.stale` | weighing bridge | `TCP_BRIDGE` | `DIAGNOSE` | bridge JSONL, GCS |
| `device.reading.captured`, `device.reading.rejected` | weighing bridge | `TCP_BRIDGE` | `RECONCILE` | bridge JSONL, GCS, ERP inbox |
| `erp.request`, `erp.response`, `erp.status`, `erp.status.error` | bridge ERP client | `HTTP_API` | `INTEGRATE` | bridge JSONL, GCS |
| `queue.enqueued`, `queue.sent`, `queue.retry`, `queue.dead` | bridge queue | `DB_CALC` | `RECONCILE` | bridge JSONL, GCS, SQLite queue |
| login/logout/password/user/entity audits | backend routers | `DB_AUDIT` | `AUTHORIZE`, `MAINTAIN` | `audit_logs`, `/activity-log` |

## 10. Known gaps and guardrails

- No retention purge job was found. Rotation caps local backend files at 10 x 10 MiB and bridge files at 5 x 5 MiB, but GCS objects and DB audit rows need a lifecycle/retention policy if retention must be bounded.
- GCS upload requires the runtime service account to have object write permission. `deploy.sh` now grants `roles/storage.objectAdmin`.
- Cloud Run local files are ephemeral; GCS upload is the durable copy. If GCS credentials are missing, local JSONL still records logs for the life of the instance.
- Backend `require_roles` is currently permissive. Treat the class matrix as intended design until `backend/app/auth.py` is fixed.
- Raw weighing payload previews are capped and disabled by default (`WEIGHING_RAW_LOG_ENABLED=false`, `WEIGHING_RAW_LOG_MAX_BYTES=64`).
- Machine transport placeholders in `backend/app/services/machine_integration.py` remain placeholders; the active integration path is the separate bridge process posting to ERP APIs.
- No tests, migrations or live production transactions were run for this documentation/logging update. Static checks only.

## 11. Verification commands

```powershell
python -m py_compile backend\app\config.py backend\app\logging_setup.py backend\app\main.py backend\app\schemas.py backend\app\services\machine_integration.py backend\app\routers\production_records.py bridge\config.py bridge\main.py
bash -n deploy.sh
git diff --check
npm run build
npm run lint
```

After deployment, verify durable storage with:

```text
GET /health
GET /dashboard/summary
GET /production/machine/status
GET /activity-log/summary

Cloud Logging: search text "http.request"
GCS: gs://kalisoftai-datahub/Kalika_inventory/Logs/api/production/YYYY/MM/DD/kalika-erp.jsonl
GCS: gs://kalisoftai-datahub/Kalika_inventory/Logs/weighing/<environment>/<device-id>/YYYY/MM/DD/bridge.jsonl
```
