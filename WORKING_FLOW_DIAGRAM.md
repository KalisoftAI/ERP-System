# Kalika ERP — Complete Working Flow Diagram

This document describes the end-to-end architecture, data flows, request lifecycles, and business processes of the Kalika Enterprises ERP system.

---

## 1. High-Level System Architecture

```mermaid
flowchart TD
    subgraph EXTERNAL ["External Sources"]
        GCS[("Google Cloud Storage\nDaily Report .xlsx")]
        ADMIN["Admin / Operations User"]
    end

    subgraph BACKEND ["FastAPI Backend (Python 3.11)"]
        MAIN[app/main.py]
        ROUTERS["Routers (REST API)"]
        SERVICES["Services (Business Logic)"]
        AUTH["JWT + RBAC\napp/auth.py"]
        MODELS["SQLAlchemy Models\napp/models.py"]
    end

    subgraph FRONTEND ["React SPA (Vite + Tailwind)"]
        UI["React Components / Pages"]
        API_CLIENT["axios client\nlib/api.js"]
        AUTH_CTX["AuthContext"]
    end

    subgraph DATA ["Data Layer"]
        DB[("PostgreSQL\nkalika_erp")]
        STAGING[("SQLite Staging\nimport_batches/")]
        REPORTS["reports/ (CSV / Excel / PDF)"]
    end

    GCS -->|download / migrate| SERVICES
    ADMIN --> UI
    UI -->|HTTPS /api| ROUTERS
    API_CLIENT -->|Bearer JWT| ROUTERS
    ROUTERS --> AUTH
    AUTH --> MODELS
    ROUTERS --> SERVICES
    SERVICES --> MODELS
    MODELS --> DB
    SERVICES -->|v2 isolated import| STAGING
    ROUTERS -->|exports| REPORTS
    UI -->|download| REPORTS
```

---

## 2. End-to-End Data Flow

```mermaid
flowchart LR
    A["Daily Report Aug-26.xlsx\n(GCS or local data/ folder)"] --> B["Migration Service\n(services/migration.py or migration_v2.py)"]
    B --> C["Sheet-aware Parsers"]
    C --> C1[RAW MATERIAL]
    C --> C2[STORE]
    C --> C3[PRODUCTION]
    C --> C4[DISPATCH]
    C --> C5[ORDER / PLAN]
    C1 --> D[(PostgreSQL)]
    C2 --> D
    C3 --> D
    C4 --> D
    C5 --> D
    D --> E["FastAPI REST API\n(/api/*)"]
    E --> F["React Dashboard"]
    F --> G["Reports / CSV / Excel / PDF"]
```

---

## 3. Backend Request Lifecycle

```mermaid
sequenceDiagram
    participant U as Browser / User
    participant F as React SPA
    participant A as FastAPI app/main.py
    participant C as CORS Middleware
    participant J as JWT Auth
    participant R as Domain Router
    participant S as Service / CRUD
    participant DB as PostgreSQL

    U->>F: Click / Form Submit
    F->>A: HTTP GET/POST/PATCH/DELETE /api/...
    A->>C: CORS Check
    C-->>A: Allowed
    A->>J: Extract Bearer Token
    J-->>A: CurrentUser + Role
    alt Insufficient Role
        J-->>A: 403 Forbidden
    else Authorized
        A->>R: Route to module router
        R->>S: Validate schema + run business logic
        S->>DB: SQLAlchemy ORM / raw SQL
        DB-->>S: Result
        S->>DB: Audit Log / Alerts / Stock Movement
        S-->>R: Serialized response
        R-->>A: JSON Response
        A-->>F: 200 OK / Data
        F-->>U: UI Update
    end
```

---

## 4. Authentication & Authorization Flow

```mermaid
flowchart TD
    A["User opens /login"] --> B["Login Page\nReact"]
    B --> C["POST /auth/login\n{username, password}"]
    C --> D["verify_password\nbcrypt"]
    D --> E{"Valid?"}
    E -->|No| F["401 Invalid credentials"]
    E -->|Yes| G["create_access_token\nJWT HS256"]
    G --> H["Store token in\nlocalStorage"]
    H --> I["AuthContext sets user"]
    I --> J["Redirect to / Dashboard"]
    J --> K["All API calls include\nAuthorization: Bearer <token>"]
    K --> L["get_current_user\nvalidate JWT"]
    L --> M{"Role allowed?"}
    M -->|No| N["403 Forbidden"]
    M -->|Yes| O["Proceed to router"]
```

### Roles

| Role | Permissions |
|------|-------------|
| admin | Full access |
| manager | Read + write masters + transactions |
| store | Purchase receive / inventory |
| production | Production output |
| dispatch | Dispatch lines |
| viewer | Read-only |

---

## 5. Database Schema Overview

```mermaid
erDiagram
    USERS ||--o{ AUDIT_LOGS : creates
    CUSTOMERS ||--o{ SALES_ORDERS : places
    CUSTOMERS ||--o{ PLANTS : owns
    SALES_ORDERS ||--|{ SALES_ORDER_LINES : has
    SALES_ORDERS ||--o{ DISPATCHES : generates
    SALES_ORDERS ||--o{ PRODUCTION_ORDERS : schedules
    PRODUCTS ||--o{ SALES_ORDER_LINES : in
    PRODUCTS ||--o{ PURCHASE_ORDER_LINES : in
    PRODUCTS ||--o{ INVENTORY : stocked_as
    PLANTS ||--o{ INVENTORY : at
    PRODUCTS ||--o{ STOCK_MOVEMENTS : moves
    PURCHASE_ORDERS ||--|{ PURCHASE_ORDER_LINES : has
    SUPPLIERS ||--o{ PURCHASE_ORDERS : supplies
    PRODUCTION_ORDERS ||--o{ PRODUCTION_MOVEMENTS : logs
    DISPATCHES ||--|{ DISPATCH_LINES : has
    PRODUCTS ||--o{ DISPATCH_LINES : in
    PRODUCTS ||--o{ RAW_MATERIAL_BALANCES : scheduled
    PRODUCTS ||--o{ BILL_OF_MATERIALS : component_of
    BOM ||--|{ BILL_OF_MATERIALS : contains
```

---

## 6. Data Migration Flows

### 6.1 Legacy Migration (v1) — Live PostgreSQL

```mermaid
flowchart TD
    A["scripts/migrate_data.py"] --> B{"--file provided?"}
    B -->|Yes| C[Use local xlsx]
    B -->|No| D["gcs.download_excel\nfrom GCS bucket"]
    C --> E["run_migration\nservices/migration.py"]
    D --> E
    E --> F["Parse RAW MATERIAL, STORE, PRODUCTION, DISPATCH, ORDER sheets"]
    F --> G["Upsert into PostgreSQL"]
    G --> H["Write migration_logs"]
```

### 6.2 Isolated Migration (v2) — Staging First

```mermaid
flowchart TD
    A["scripts/migrate_v2.py --fresh"] --> B["Create SQLite staging DB\nbackend/data/import_batches/"]
    B --> C["excel_parser_v2.py\nParse workbook"]
    C --> D["migration_v2.py\nNormalize + alias matching"]
    D --> E["Insert into staging SQLite"]
    E --> F["validation_v2.py\nReconcile Excel vs DB"]
    F --> G{"Status"}
    G -->|READY_FOR_PROMOTION| H["Can promote to live DB\nexit 0"]
    G -->|NOT_READY| I["Report errors\nexit 1"]
    I --> J["reports/validation_batch_*.json"]
    H --> J
```

---

## 7. Purchase Order → Inventory Flow

```mermaid
sequenceDiagram
    participant M as Manager
    participant R as /purchases Router
    participant S as Purchase Service
    participant DB as PostgreSQL

    M->>R: POST /purchases (create PO + lines)
    R->>S: Validate schemas
    S->>DB: INSERT purchase_order
    S->>DB: INSERT purchase_order_lines
    S->>DB: INSERT audit_log
    S-->>R: PO response
    R-->>M: 201 Created

    M->>R: POST /purchases/{id}/receive
    R->>S: Receive quantity
    S->>DB: UPDATE line.received_qty
    S->>DB: UPDATE inventory.current_stock += delta
    S->>DB: UPDATE inventory.received_qty += delta
    S->>DB: INSERT stock_movement (PURCHASE_RECEIPT)
    S->>DB: Recalculate PO status
    S->>DB: INSERT audit_log
    S-->>R: Updated PO
    R-->>M: 200 OK
```

---

## 8. Sales Order Lifecycle

```mermaid
stateDiagram-v2
    [*] --> New : Create Order
    New --> Confirmed : Confirm
    Confirmed --> In_Production : Manufactured product
    Confirmed --> On_Purchase : Trading product
    In_Production --> Ready : Production completed
    On_Purchase --> Ready : Stock available
    Ready --> Dispatched : Dispatch created
    Dispatched --> Completed : Fully delivered
    New --> Cancelled
    Confirmed --> Cancelled
    In_Production --> Cancelled
    Ready --> Partially_Dispatched
    Partially_Dispatched --> Dispatched
    Partially_Dispatched --> Completed
```

### Automatic Status Recomputation

```mermaid
flowchart TD
    A["recompute_order_statuses\nservices/business.py"] --> B["For each active order line"]
    B --> C["balance = ordered - dispatched"]
    C --> D{"balance <= 0?"}
    D -->|Yes| E["completed"]
    D -->|No| F["available = inventory.current_stock"]
    F --> G{"available >= balance?"}
    G -->|Yes| H["ready"]
    G -->|No| I{"source_type"}
    I -->|MANUFACTURED| J["in_production"]
    I -->|TRADING| K["on_purchase"]
    I -->|OTHER| L["confirmed"]
    E --> M["Aggregate to order status"]
    H --> M
    J --> M
    K --> M
    L --> M
    M --> N["Update sales_orders.status\n(only advances, never regresses)"]
```

---

## 9. Production → Dispatch Flow

```mermaid
sequenceDiagram
    participant P as Production User
    participant PR as /production Router
    participant PS as Production Service
    participant DB as PostgreSQL

    P->>PR: POST /production (create order)
    PR->>PS: Validate + create
    PS->>DB: INSERT production_order
    PS->>DB: INSERT audit_log
    PS-->>PR: Order created
    PR-->>P: 201 Created

    P->>PR: POST /production/{id}/movements
    PR->>PS: Record output qty
    PS->>DB: INSERT production_movement
    PS->>DB: UPDATE production_order.produced_qty
    PS->>DB: UPDATE inventory.current_stock += qty
    PS->>DB: INSERT stock_movement (PRODUCTION_OUTPUT)
    PS->>DB: INSERT audit_log
    PS-->>PR: Updated order
    PR-->>P: 200 OK

    participant D as Dispatch User
    participant DR as /dispatch Router
    participant DS as Dispatch Service

    D->>DR: POST /dispatch (create dispatch)
    DR->>DS: Validate + create
    DS->>DB: INSERT dispatch
    DS->>DB: INSERT audit_log
    DS-->>DR: Dispatch created
    DR-->>D: 201 Created

    D->>DR: POST /dispatch/{id}/lines
    DR->>DS: Add dispatch line
    DS->>DB: INSERT dispatch_line
    DS->>DB: UPDATE inventory.current_stock -= qty
    DS->>DB: UPDATE inventory.issued_qty += qty
    DS->>DB: INSERT stock_movement (DISPATCH)
    DS->>DB: UPDATE sales_order status
    DS->>DB: INSERT audit_log
    DS-->>DR: Line added
    DR-->>D: 200 OK
```

---

## 10. Alert & Requirement Engine

```mermaid
flowchart TD
    A["sync_purchase_shortages\non startup / mutation"] --> B["Scan non-cancelled order lines"]
    B --> C["balance = ordered - dispatched"]
    C --> D{"LOCAL order?"}
    D -->|Yes| E["available = all_location_stock"]
    D -->|No| F["available = main_store_stock"]
    E --> G["shortage = balance - available"]
    F --> G
    G --> H{"shortage > 0?"}
    H -->|No| I["Resolve stale alerts / requirements"]
    H -->|Yes| J{"source_type"}
    J -->|TRADING| K["Upsert PurchaseRequirement\nCATEGORY=PURCHASE"]
    J -->|MANUFACTURED| L["Upsert PurchaseRequirement\nCATEGORY=PRODUCTION"]
    J -->|MIXED/UNKNOWN| M["Manual decision surfaced in UI"]
    K --> N["ensure_alert\nPURCHASE_REQUIRED"]
    L --> O["ensure_alert\nPRODUCTION_MATERIAL_SHORTAGE"]

    P["Raw material min_stock update"] --> Q["refresh_reorder_alert"]
    Q --> R{"current < min?"}
    R -->|Yes| S["Create OPEN\nSTOCK_SHORTAGE alert"]
    R -->|No| T["Resolve alert"]
```

---

## 11. Stock Flow & Internal Transfers

```mermaid
flowchart LR
    subgraph LOCATIONS ["Stock Locations"]
        MS["Main Store\nplant_id = NULL"]
        DP["Dispatch Plant"]
        PRD["Production Plant"]
        CP["Customer Plant"]
    end

    MS -->|Stock Transfer| DP
    MS -->|Stock Transfer| PRD
    DP -->|Customer Dispatch| CP
    PRD -->|Production Output| MS

    subgraph MOVEMENTS ["Stock Movement Types"]
        M1[PURCHASE_RECEIPT]
        M2[PRODUCTION_OUTPUT]
        M3[DISPATCH]
        M4[TRANSFER]
        M5[ADJUSTMENT]
    end
```

---

## 12. Dashboard & Reports Flow

```mermaid
flowchart TD
    A["User opens Dashboard"] --> B["GET /dashboard/summary"]
    A --> C["GET /dashboard/order-pipeline"]
    A --> D["GET /dashboard/production-by-product"]
    A --> E["GET /dashboard/dispatch-by-plant"]
    A --> F["GET /dashboard/inventory-status"]
    A --> G["GET /dashboard/raw-material-stock"]
    A --> H["GET /dashboard/daily-trends"]
    A --> I["GET /dashboard/low-stock-list"]

    B --> DB[(PostgreSQL)]
    C --> DB
    D --> DB
    E --> DB
    F --> DB
    G --> DB
    H --> DB
    I --> DB

    J["User clicks Reports"] --> K["GET /reports/excel"]
    J --> L["GET /reports/{module}/csv"]
    J --> M["GET /reports/orders/{id}/pdf"]
    J --> N["GET /reports/delivery"]
    K --> DB
    L --> DB
    M --> DB
    N --> DB
```

---

## 13. Frontend Routing Flow

```mermaid
flowchart TD
    A["Browser URL"] --> B{"Authenticated?"}
    B -->|No| C["/login"]
    B -->|Yes| D["Layout with Sidebar"]
    D --> E["/ Dashboard"]
    D --> F["/raw-materials"]
    D --> G["/purchases"]
    D --> H["/inventory"]
    D --> I["/stock-movements"]
    D --> J["/production"]
    D --> K["/orders"]
    D --> L["/dispatch"]
    D --> M["/pending-po"]
    D --> N["/requirements"]
    D --> O["/bom"]
    D --> P["/material-requirements"]
    D --> Q["/fulfilment"]
    D --> R["/alerts"]
    D --> S["/local-orders"]
    D --> T["/customers"]
    D --> U["/suppliers"]
    D --> V["/reports"]
    D --> W["/users"]
```

---

## 14. Deployment & CI/CD Flow

```mermaid
flowchart TD
    A["Developer pushes code"] --> B["Cloud Build Trigger"]
    B --> C["cloudbuild.yaml"]
    C --> D["docker build"]
    D --> E["Multi-stage Dockerfile"]
    E --> E1["Stage 1: npm install + npm run build\nReact -> frontend/dist"]
    E --> E2["Stage 2: pip install + copy backend\n+ frontend/dist"]
    E2 --> F["Push image to\nArtifact Registry"]
    F --> G["Cloud Run deploy"]
    G --> H["Container starts uvicorn\nPORT 8080"]
    H --> I["FastAPI serves API + built SPA"]
    I --> J[(Cloud SQL PostgreSQL)]
```

### Local Development Flow

```mermaid
flowchart LR
    A["npm run dev\nVite localhost:5173"] -->|/api/* proxy| B["uvicorn localhost:8000"]
    B --> C[(PostgreSQL local)]
    D["python scripts/init_db.py"] --> C
    E["python scripts/migrate_data.py"] --> C
```

---

## 15. Startup Sequence

```mermaid
flowchart TD
    A["uvicorn app.main:app"] --> B["FastAPI startup event"]
    B --> C["Base.metadata.create_all"]
    C --> D["_ensure_columns"]
    D --> E["_ensure_order_status_enum"]
    E --> F["_ensure_number_indexes"]
    F --> G["_ensure_locations"]
    G --> H["_ensure_inventory_unique"]
    H --> I["sync_purchase_shortages"]
    I --> J["App ready\nHealth check /health"]
```

---

## 16. Module → Router Mapping

| Module | Router File | Prefix |
|--------|-------------|--------|
| Auth | `app/routers/auth.py` | `/auth` |
| Users | `app/routers/users.py` | `/users` |
| Customers | `app/routers/customers.py` | `/customers` |
| Suppliers | `app/routers/suppliers.py` | `/suppliers` |
| Products | `app/routers/products.py` | `/products` |
| Plants | `app/routers/plants.py` | `/plants` |
| Raw Materials | `app/routers/raw_materials.py` | `/raw-materials` |
| Purchases | `app/routers/purchases.py` | `/purchases` |
| Inventory | `app/routers/inventory.py` | `/inventory` |
| Stock Flow | `app/routers/stock_flow.py` | `/stock-locations`, `/stock-transfers`, `/customer-dispatches` |
| Production | `app/routers/production.py` | `/production` |
| Orders | `app/routers/orders.py` | `/orders` |
| Dispatch | `app/routers/dispatch.py` | `/dispatch` |
| Plans | `app/routers/plans.py` | `/plans` |
| Requirements | `app/routers/requirements.py` | `/requirements` |
| Material Requirements | `app/routers/material_requirements.py` | `/material-requirements` |
| Fulfilment | `app/routers/fulfilment.py` | `/fulfilment` |
| Local Orders | `app/routers/local_orders.py` | `/local-orders` |
| BOM | `app/routers/bom.py` | `/bom` |
| Alerts | `app/routers/alerts.py` | `/alerts` |
| Dashboard | `app/routers/dashboard.py` | `/dashboard` |
| Reports | `app/routers/reports.py` | `/reports` |
| Meta | `app/routers/meta.py` | `/meta` |
| Salespersons | `app/routers/salespersons.py` | `/salespersons` |

---

## 17. Key Business Rules

1. **Inventory is dual-tracked**: `current_stock = opening_stock + received_qty - issued_qty`.
2. **Every stock-changing operation** creates a `stock_movement` row.
3. **Sales order status** is auto-recomputed from real signals and only advances forward.
4. **Purchase requirements** are generated from genuine shortages; LOCAL orders use all-location stock.
5. **Raw material alerts** fire when `current_stock < min_stock`.
6. **SO/PO numbers** are business references, not unique keys; internal `id` is the system key.
7. **Audit logs** are written on every mutating API call.
8. **v2 migration** never touches the live DB; it validates in SQLite staging first.

---

*Generated for Kalika Enterprises ERP.*
