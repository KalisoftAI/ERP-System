# Weighing Machine + TSC Label Printer — Configuration Extract & Integration Roadmap

## 1. Extracted configuration (normalized)

| # | Component | Specification | Integration requirement | Status |
|---|-----------|---------------|-------------------------|--------|
| 1 | Weighing machine | Indicator + weighing platform | Capture measured weight | Confirmed |
| 2 | Printer | TSC Label 244 Pro (TSPL) | Print product and weight labels | Confirmed |
| 3 | Label width | 100 mm | Configure label dimensions | Confirmed |
| 4 | Label type | Non-transparent labels with gap paper | Configure gap sensing | Confirmed |
| 5 | Communication cable | RS232, 2 metres | Connect indicator to interface | Confirmed |
| 6 | Capacity | NA | Obtain from weighing-machine manufacturer | **Missing** |
| 7 | Accuracy / division | NA | Obtain approved measurement specification | **Missing** |
| 8 | Platform size | NA | Obtain from manufacturer | **Missing** |
| 9 | Power supply | Not specified | Verify requirements of each device | **Missing** |
| 10 | Label height / gap | Not specified | Needed for TSPL `SIZE` + `GAP` | **Missing** |
| 11 | Indicator protocol | Not specified | Baud, parity, frame format, stable bit | **Missing** |
| 12 | Barcode content | Not specified | Decide GTIN / lot / serial encoding | **Missing** |

> The source text repeats the same **"Electronics Module Printer TSC Label 244 Pro..."** line twice. Confirm whether that is **quantity 2** or a copy/paste duplicate.

> "TSC Label 244 Pro" is normally the **TSC TTP-244 Pro** (203 dpi, 104 mm max print width, RS232 + USB + parallel, TSPL-EZ). 100 mm media is within range. "Non-transparent with gap paper" means **transmissive gap sensor**, not black-mark/reflective mode.

---

## 2. Physical topology

The 2 m RS232 cable cannot connect the indicator directly to the printer as a data path — the printer is an output device. The indicator must talk to a **PC / edge gateway**, which then drives the printer.

```
                        RS232, 2 m (8N1, no flow control)
+-------------------+   DB9 / COM / USB-serial    +---------------------------+
| Weighing machine  |<--------------------------->|  Edge Gateway / PC        |
| - indicator       |    continuous or on-demand   |  - serial listener        |
| - platform        |    ASCII weight frames       |  - parser + stability gate|
+-------------------+                              |  - label composer (TSPL)  |
        ^                                          |  - offline retry queue    |
        | load cell cable                          +------+-------------+------+
        |                                                 |             |
        |                                        REST/HTTPS|            USB/RAW
        |                                                 v             v
        |                                     +-----------+--+   +------+-----------+
        |                                     | ERP Backend  |   | TSC TTP-244 Pro  |
        |                                     | API + DB     |   | 100 mm gap labels|
        |                                     +--------------+   +------------------+
        |
   [Power: verify separately — do not power printer from indicator]
```

### Wiring / interface checklist

```
Indicator DB9            Gateway / adapter             TSC TTP-244 Pro
-----------              -----------------             ---------------
TXD (pin 3) --->         RXD                           RS232 DB9 (verify gender)
RXD (pin 2) <---         TXD                           or USB (recommended)
GND (pin 5) ---          GND                           Gap sensor enabled
                         Shield / earth                DENSITY 8, SPEED 4
```

- Confirm whether indicator and printer port are **DTE or DCE**; use a **null-modem** adapter if both are DTE.
- Prefer a **USB-to-RS232 adapter with FTDI chipset** over unbranded CH340 for stable continuous reading.
- 2 m is well inside RS232 limits, but keep the cable away from AC/motor lines.
- Use **USB from gateway to printer** unless the printer serial port is required; USB removes baud mismatch risk.

---

## 3. System data flow

```
Operator        Gateway / Agent          Indicator        ERP API          Printer
   |                  |                      |                |                |
   | place item       |                      |                |                |
   |----------------->|                      |                |                |
   |                  | open COM, read frames|                |                |
   |                  |<---------------------|                |                |
   |                  | parse gross/net/tare |                |                |
   |                  | stable >= 500 ms?    |                |                |
   |                  |-- no: discard -------|                |                |
   | press PRINT      |                      |                |                |
   |----------------->|                      |                |                |
   |                  | GET /products?sku=   |                |                |
   |                  |------------------------------------->|                |
   |                  |<-------------------------------------|                |
   |                  | POST /weighments     |                |                |
   |                  |------------------------------------->|                |
   |                  |<------------- 201 {id} ---------------|                |
   |                  | build TSPL payload   |                |                |
   |                  |---------------------------------------------------->|
   |                  |<------------------- ACK / status --------------------|
   |                  | POST /print-jobs     |                |                |
   |                  |------------------------------------->|                |
   |<-- label --------|                      |                |                |
```

Key rule: **the weight is frozen at the moment "PRINT" is pressed**, stored in ERP, then printed. Reprinting must use the stored weight, never a live reading.

---

## 4. Data model

```
+--------------------+        +----------------------+        +---------------------+
| devices            |        | weighment_sessions   |        | label_print_jobs    |
+--------------------+        +----------------------+        +---------------------+
| id                 |<-------| device_id            |        | id                  |
| code               |        | id                   |<-------| weighment_id        |
| kind SCALE/PRINTER |        | product_id --------->|products| template_id ------> |
| port / baud / parity|       | lot_no               |        | status              |
| label_template_id --------> | gross, tare, net     |        | tspl_payload        |
| active             |        | unit                 |        | printer_response    |
+--------------------+        | is_stable            |        | attempt_count       |
                              | operator_id          |        | idempotency_key     |
                              | captured_at          |        | printed_at          |
                              | raw_frame            |        +---------------------+
                              +----------------------+
                                        ^
                                        |
                              +----------------------+
                              | label_templates      |
                              +----------------------+
                              | id, name             |
                              | width_mm = 100       |
                              | height_mm = TBD      |
                              | gap_mm = TBD         |
                              | dpi = 203            |
                              | sensor = GAP         |
                              | fields_json          |
                              +----------------------+
```

### Proposed fields

| Table | Field | Type | Notes |
|-------|-------|------|-------|
| `weighment_sessions` | `gross_weight` | `NUMERIC(12,3)` | Match indicator division |
| | `tare_weight` | `NUMERIC(12,3)` | 0 if indicator tared |
| | `net_weight` | `NUMERIC(12,3)` | Server-side `gross - tare` |
| | `unit` | `VARCHAR(4)` | `kg` / `g` / `t` |
| | `is_stable` | `BOOLEAN` | Must be true to print |
| | `raw_frame` | `TEXT` | Audit / replay |
| | `product_id`, `lot_no` | FK / text | Label identity |
| `label_print_jobs` | `status` | `ENUM` | `QUEUED / SENT / PRINTED / FAILED` |
| | `idempotency_key` | `VARCHAR(64)` | Prevent duplicate prints |
| | `tspl_payload` | `TEXT` | Exact bytes sent |
| `devices` | `port`, `baud`, `parity`, `data_bits`, `stop_bits` | | Per-device config |

---

## 5. Serial capture rules

```
Port      : COMx (USB-serial) or native COM
Baud      : TBD from indicator manual (commonly 9600 / 19200 / 38400)
Data bits : 7 or 8
Parity    : None or Even
Stop bits : 1
Flow      : None
Delimiter : CR / LF / CRLF
Mode      : continuous stream OR on-demand request
```

Typical frame examples to support:

```
ST,GS,+  12.345 kg      stable gross
US,GS,+  12.301 kg      unstable -> reject
OL,GS,+  ------ kg      overload -> reject
NT,GS,+  12.345 kg      net mode
```

Parser rules:

1. Read frame delimited by CR/LF.
2. Extract **status** (`ST`/`US`/`OL`), **mode** (`GS`/`NT`), **sign**, **value**, **unit**.
3. Reject if not `ST`, if `OL`, or if value unchanged but status unstable.
4. Require stability for **>= 500 ms** before enabling PRINT.
5. Store `raw_frame` exactly; never re-derive stored weight from the live scale.
6. Convert unit at the edge only if the indicator and label agree; record both.

---

## 6. Label design (100 mm)

```
+--------------------------------------------------------+  <- 100 mm media width
|  KALIKA ENTERPRISES                        [ LOGO ]     |
|                                                         |
|  Product : ___________________________________________  |
|  Model/SKU: __________________________________________  |
|  Batch/Lot: ______________     Date: ________________  |
|                                                         |
|  +---------------------------------------------------+  |
|  |                  GROSS WEIGHT                     |  |
|  |                    12.345 kg                      |  |
|  +---------------------------------------------------+  |
|                                                         |
|  Tare: 0.000 kg          Net: 12.345 kg                 |
|                                                         |
|  |||||||||||||||||||||||||||||||||||||||||||||          |
|  || 8 9 0 1 2 3 4 5 6 7 8 9 0 ||                        |
|                                                         |
|  Operator: ________   Shift: ____   Line: ____          |
+--------------------------------------------------------+
   ~~~~~~~~~~~~ gap paper / liner ~~~~~~~~~~~~~~~~~~~~
```

- Label **height** and **gap size** must be measured from a physical roll before final template sign-off.
- Because labels are **non-transparent**, set the printer to **gap (transmissive) sensing**. Do not use black-mark mode unless the roll has marks.
- Decimal places on the label must equal the indicator **division**; do not invent precision (e.g. do not print `12.3450` if division is `0.01 kg`).

### TSPL template skeleton

```
SIZE 100 mm, 50 mm          ; height TBD after roll measurement
GAP 2 mm, 0 mm              ; gap TBD after roll measurement
DIRECTION 1
REFERENCE 0,0
DENSITY 8
SPEED 4
CLS
TEXT 20,20,"3",0,1,1,"KALIKA ENTERPRISES"
TEXT 20,60,"2",0,1,1,"Product: {{product_name}}"
TEXT 20,90,"2",0,1,1,"Model: {{model}}"
TEXT 20,120,"2",0,1,1,"Lot: {{lot_no}}   Date: {{date}}"
TEXT 40,180,"3",0,1,1,"GROSS WEIGHT"
TEXT 60,220,"4",0,2,2,"{{gross}} {{unit}}"
TEXT 20,300,"2",0,1,1,"Tare: {{tare}} {{unit}}  Net: {{net}} {{unit}}"
BARCODE 20,340,"128",80,1,0,2,4,"{{barcode}}"
TEXT 20,440,"2",0,1,1,"Operator: {{operator}}  Shift: {{shift}}"
PRINT 1,1
```

`{{placeholders}}` are substituted by the gateway before sending; TSPL itself does not interpolate arbitrary variables.

---

## 7. ERP API surface

```
GET  /api/devices
GET  /api/label-templates/{id}
GET  /api/products?sku={sku}
POST /api/weighments
GET  /api/weighments/{id}
POST /api/weighments/{id}/print
POST /api/print-jobs/{id}/ack
GET  /api/print-jobs?status=FAILED
```

`POST /api/weighments` example:

```json
{
  "device_id": 7,
  "product_id": 1042,
  "lot_no": "LOT-2026-11-001",
  "gross_weight": 12.345,
  "tare_weight": 0.0,
  "net_weight": 12.345,
  "unit": "kg",
  "is_stable": true,
  "raw_frame": "ST,GS,+  12.345 kg",
  "captured_at": "2026-11-02T10:15:22Z",
  "idempotency_key": "SCALE7-20261102-101522-12345"
}
```

`POST /api/weighments/{id}/print` returns:

```json
{
  "print_job_id": 991,
  "status": "QUEUED",
  "template": "product-weight-100mm-v1",
  "tspl_ref": "sha256:..."
}
```

---

## 8. Print workflow state machine

```
        +--------+   capture    +----------+   print    +---------+
        | IDLE   |------------->| CAPTURED |----------->| QUEUED  |
        +--------+              +----------+            +---------+
            ^                        |                      |
            | reset/cancel           | reject               | send TSPL
            |                        v                      v
            |                   +----------+          +----------+
            +-------------------| REJECTED |          |  SENT    |
                                 +----------+          +----+-----+
                                                            |
                                          printer ACK ------+------ no ACK
                                                |                    |
                                                v                    v
                                          +----------+        +----------+
                                          | PRINTED  |        |  FAILED  |
                                          +----------+        +----+-----+
                                                |                  |
                                                |           retry / manual
                                                v                  v
                                          +----------+        +----------+
                                          | AUDITED  |        | REPRINT  |
                                          +----------+        +----------+
```

Mandatory rules:

- No print without `is_stable = true`.
- No print without a resolved ERP weight record.
- Retries use the stored weight and payload, never a fresh reading.
- Every print attempt is audit-logged with operator, device, timestamp, and payload hash.

---

## 9. Phased roadmap

```
Phase 0  Discovery & sign-off      W1     [####]
Phase 1  Hardware bench setup      W1-W2  [    #####]
Phase 2  Serial capture service    W2-W3  [      ######]
Phase 3  Data model + API          W3-W4  [        ######]
Phase 4  Label template + TSPL     W4     [          ####]
Phase 5  Operator UI + workflow    W5     [            ######]
Phase 6  UAT + calibration         W6     [                #####]
Phase 7  Rollout + SOP + support   W6-W7  [                  #####]
```

| Phase | Deliverables | Exit criteria |
|-------|--------------|---------------|
| **0 — Discovery** | Indicator make/model, manual, serial protocol, capacity, division, platform size, power, label height/gap, barcode spec | All NA items replaced with confirmed values; signed config sheet |
| **1 — Hardware** | Bench setup: indicator, gateway, printer, 2 m RS232, USB printer link | Stable weight frames captured in a terminal; test label prints |
| **2 — Capture service** | COM listener, parser, stability gate, unit handling, reconnect logic | 8-hour soak with zero missed stable readings; unplug/replug recovers |
| **3 — Data + API** | `devices`, `weighment_sessions`, `label_templates`, `label_print_jobs`; endpoints | API tests pass; stored weight equals displayed weight |
| **4 — Label** | 100 mm template, gap sensor config, TSPL payload builder | 50 consecutive labels align, scan correctly, no drift |
| **5 — UI/workflow** | Product selection, lot entry, live weight display, PRINT, reprint | Operator completes one label in <= 15 seconds |
| **6 — UAT** | Calibration check, accuracy against approved division, error-path tests | UAT signed by operations + quality |
| **7 — Rollout** | SOP, training, spares (labels, ribbon, USB-serial adapter), monitoring | First production shift completed without support escalation |

---

## 10. Test and acceptance checklist

- [ ] Weight on label equals indicator display at the same moment
- [ ] Unstable/overload frames are rejected and cannot print
- [ ] Tare and net are handled correctly
- [ ] Unit is consistent between indicator, label, and ERP
- [ ] Decimal places match the approved division
- [ ] 100 mm label prints without clipping; gap sensor stops at each gap
- [ ] Barcode scans at first attempt on 20 consecutive labels
- [ ] Reprint uses stored weight, not live weight
- [ ] Duplicate PRINT is blocked or explicitly marked `REPRINT`
- [ ] Printer offline produces `FAILED`, not silent loss
- [ ] COM disconnect/reconnect recovers automatically
- [ ] Power cycle of indicator, printer, and gateway loses no queued job
- [ ] Audit log reconstructs every printed label byte-for-byte
- [ ] 8-hour production soak passes

---

## 11. Risks and decisions required

| Risk / decision | Impact | Action |
|-----------------|--------|--------|
| Indicator model and protocol unknown | Cannot write parser | Obtain manual and sample frames |
| Capacity, division, platform size are NA | Label precision and legal metrology uncertain | Get manufacturer datasheet / calibration certificate |
| Label height and gap unknown | TSPL `SIZE`/`GAP` cannot be finalized | Measure physical roll |
| "Non-transparent with gap paper" | Wrong sensor mode causes drift | Confirm **gap sensor**, not black mark |
| Duplicate line item in source | Possible qty ambiguity | Confirm quantity 1 or 2 |
| RS232 endpoint ambiguity | Wrong cable/adapter purchased | Confirm indicator port and gateway port; DTE/DCE |
| Power unspecified | Device damage / instability | Verify voltage, current, adapter per device |
| Weight used for trade? | Legal metrology approval may apply | Confirm use case with quality/compliance |
| Printer is TSPL, not ZPL | ZPL templates will fail | Build TSPL-EZ payloads; test on actual unit |

---

## 12. Minimal build order (if starting today)

1. Get the indicator manual and capture one raw weight frame.
2. Bench-test: indicator -> USB-serial -> PC terminal -> printer USB.
3. Freeze a 100 mm label template with measured height/gap.
4. Add `weighment_sessions` + `label_print_jobs` + API.
5. Build the edge agent: read, stabilize, POST, print, ack, retry.
6. Add operator screen and reprint/audit.
7. UAT against approved division, then SOP and rollout.
