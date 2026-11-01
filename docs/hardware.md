# Barrier & gate-controller integration

GateVision never talks to hardware directly from a router. The decision engine
produces a decision, and the **barrier actuator** for that compound carries it
to the physical gate. Four drivers ship out of the box:

| Driver | Transport | Use it for |
| --- | --- | --- |
| `simulator` | none (in-process) | demos, CI and staging; configurable latency/failure rate |
| `webhook` | HTTPS POST | controller boards and relay modules with a small HTTP API (Shelly, ESPHome, Node-RED, ...) |
| `mqtt` | MQTT publish | PLCs, ESP32 relay boards and industrial gateways already on a broker |
| `gpio` | GPIO pulse (gpiozero) | a Raspberry Pi wired straight to the barrier's dry-contact input |

Every attempt is journaled (`/api/v1/cv/actuators`), broadcast on the
`gate.command` WebSocket event and written to the application log with the
driver, latency, attempt count and failure reason.

---

## 1. Choosing a driver

Drivers are configured **per compound** so two compounds can use different
hardware:

```bash
curl -X PATCH https://gatevision.local/api/v1/compounds/$COMPOUND_ID/settings \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "barrier": {
          "driver": "webhook",
          "webhook": {
            "url": "https://controller.ramses-1.local/api/barrier",
            "secret": "copy-this-to-the-controller",
            "timeout_seconds": 3,
            "retries": 2,
            "verify_tls": true
          }
        }
      }'
```

Secrets are masked (`********`) when read back through the API. Read the
effective configuration at any time:

```bash
curl -s https://gatevision.local/api/v1/cv/actuators?compound_id=$COMPOUND_ID \
  -H "Authorization: Bearer $MANAGER_TOKEN" | jq
```

The same values can be seeded through the environment for every compound:

```bash
BARRIER_DRIVER=webhook
BARRIER_WEBHOOK_URL=https://controller.ramses-1.local/api/barrier
BARRIER_WEBHOOK_SECRET=copy-this-to-the-controller
```

A compound policy always wins over the environment defaults.

### Sending a test command

```bash
curl -X POST https://gatevision.local/api/v1/cv/actuators/test \
  -H "Authorization: Bearer $MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"gate_id": "'$GATE_ID'", "action": "open"}'
```

The response contains the driver, latency and journaled `command_id`. Invalid
actions are rejected with `422` before any hardware is touched.

---

## 2. HTTP webhook driver

### Request

```
POST /api/barrier HTTP/1.1
Host: controller.ramses-1.local
Content-Type: application/json
User-Agent: GateVision-Barrier/1.0
X-GateVision-Timestamp: 1767225600
X-GateVision-Event-Id: 4a1d…-uuid
X-GateVision-Action: open
X-GateVision-Signature: sha256=8fae…

{"event_id":"4a1d…","gate":"GATE-IN","action":"open",
 "reason":"Registered resident vehicle","issued_at":"2026-11-01T10:00:00+00:00",
 "source":"gatevision"}
```

`X-GateVision-Signature` is `HMAC-SHA256(secret, "<timestamp>.<raw body>")`.
Verify it **before** energising the relay and reject timestamps older than 60
seconds to stop replays.

### Verifying the signature (Python)

```python
import hashlib, hmac
from flask import Flask, request, abort

app = Flask(__name__)
SECRET = b"copy-this-to-the-controller"

@app.post("/api/barrier")
def barrier():
    timestamp = request.headers["X-GateVision-Timestamp"]
    expected = hmac.new(
        SECRET, timestamp.encode() + b"." + request.get_data(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(request.headers["X-GateVision-Signature"], f"sha256={expected}"):
        abort(401)
    command = request.get_json()
    if command["action"] == "open":
        pulse_relay(17)
    return {"ok": True}
```

### Verifying the signature (Node-RED / JavaScript)

```js
const crypto = require("crypto");
const expected = "sha256=" + crypto
  .createHmac("sha256", process.env.GATEVISION_SECRET)
  .update(msg.payload.timestamp + "." + msg.payload.rawBody)
  .digest("hex");
if (!crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(msg.payload.signature))) {
  node.status({ fill: "red", text: "bad signature" });
  return null;
}
```

### Retry semantics

| Controller response | GateVision behaviour |
| --- | --- |
| `2xx` / `3xx` | command accepted |
| `429` or `5xx` | retried with exponential backoff (0.25 s, 0.5 s, … up to 4 s) |
| `4xx` | **not** retried (bad request/authorisation) |
| timeout / DNS / TLS error | retried, then reported as failed |

A controller must respond in under `timeout_seconds` (default 3 s) and should
answer `202` as soon as the relay is energised — GateVision does not wait for
the barrier arm to physically move.

---

## 3. MQTT driver

```bash
PATCH /api/v1/compounds/{id}/settings
{"barrier": {"driver": "mqtt", "mqtt": {
   "host": "mqtt.ramses-1.local", "port": 1883,
   "topic": "gatevision/{gate}/command", "qos": 1,
   "username": "gatevision", "password": "…", "tls": false,
   "simulate": false}}}
```

Topic placeholders: `{gate}` → gate code (`GATE-IN`), `{compound}` →
`default`. Payload:

```json
{"event_id":"4a1d…","gate":"GATE-IN","action":"open",
 "reason":"Valid visitor permit","issued_at":"2026-11-01T10:00:00+00:00",
 "source":"gatevision"}
```

Subscribe on the controller with QoS 1 and enforce idempotency on `event_id`
(the broker may deliver duplicates). `simulate: true` logs the publish without
needing a broker; install the client with
`pip install -r requirements-cv.txt` (includes `paho-mqtt`).

Minimal ESP32 subscriber (Arduino):

```cpp
#include <WiFi.h>
#include <PubSubClient.h>

const char* TOPIC = "gatevision/GATE-IN/command";
const int RELAY_PIN = 17;

void callback(char* topic, byte* payload, unsigned int length) {
  String body;
  for (unsigned int i = 0; i < length; i++) body += (char)payload[i];
  if (body.indexOf("\"action\":\"open\"") >= 0) {
    digitalWrite(RELAY_PIN, HIGH);
    delay(600);                 // pulse length — match gpio.pulse_seconds
    digitalWrite(RELAY_PIN, LOW);
  }
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  WiFi.begin("ssid", "password");
  mqtt.setServer("mqtt.ramses-1.local", 1883);
  mqtt.setCallback(callback);
  mqtt.connect("barrier-gate-in");
  mqtt.subscribe(TOPIC, 1);
}
```

---

## 4. GPIO / relay driver (Raspberry Pi)

```bash
PATCH /api/v1/compounds/{id}/settings
{"barrier": {"driver": "gpio", "gpio": {
   "open_pin": 17, "close_pin": 27, "hold_pin": 22,
   "active_high": true, "pulse_seconds": 0.6, "simulate": false}}}
```

Wiring (typical 2-channel relay board):

```
Raspberry Pi GPIO17  ──► relay IN1   relay COM/NO ──► barrier "OPEN" dry contact
Raspberry Pi GPIO27  ──► relay IN2   relay COM/NO ──► barrier "CLOSE" dry contact
Raspberry Pi GPIO22  ──► relay IN3   relay COM/NO ──► barrier "HOLD" dry contact
Raspberry Pi GND     ──► relay GND/VCC (use an external 5 V supply for the coil)
```

* `open`/`close` energise the relay for `pulse_seconds`, then release it.
* `hold` keeps the relay energised for at least 3 seconds and falls back to the
  open pin when `hold_pin` is not wired.
* `active_high: false` inverts the logic for active-low relay boards.
* Run the API as a user in the `gpio` group (`usermod -aG gpio gatevision`).
* `simulate: true` (default) logs the pulse, so the same configuration works on
  a laptop.

---

## 5. Monitoring and troubleshooting

```bash
# Driver, health, recent commands and global journal counters
curl -s .../api/v1/cv/actuators | jq '.compounds[0].recent_commands[0]'

# Durable audit trail of every decision + gate_opened flag
curl -s .../api/v1/access-logs?page_size=5 | jq '.items[] | {occurred_at, decision, gate_opened}'
```

Log lines are structured and greppable:

```
Barrier command gate=GATE-IN action=open driver=webhook accepted=True latency=142ms actor=officer@gatevision.app detail=Webhook accepted open on GATE-IN (HTTP 202, 1 attempt(s))
```

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `accepted=false`, `detail` mentions `HTTP 401/403` | controller rejected the signature | re-copy `webhook.secret` on both sides, check clock skew |
| `ConnectError` / timeout | controller unreachable from the API host | `curl` the URL from inside the API container |
| `dependency_missing` | `paho-mqtt` / `gpiozero` not installed | `pip install -r requirements-cv.txt` or enable `simulate` |
| barrier opens but the log says not opened | controller answered after the timeout | raise `timeout_seconds`, or return `202` immediately |
| relay clicks twice | retries after a slow `2xx` response | return `202` before pulsing, or set `retries: 0` |

If a command fails, the access log still records the decision; only
`gate_opened` is `false`, so failed openings are visible in analytics and the
`gate.command` event payload carries the error detail.
