---
name: bambu-printer-mqtt
description: "Use when controlling Bambu Lab printers (A1, P1, X1) via cloud or local MQTT. Covers login, device discovery, report structure and the firmware command-signature pitfall."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [3d-printing, bambu-lab, mqtt, home-automation]
---

# Bambu Lab printers via MQTT

Read status and send commands to Bambu Lab printers (A1 / A1 Mini / P1P / P1S / X1C) without Bambu Studio or Bambu Handy.
Protocol reference: [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI).

## Option A: Cloud MQTT (no LAN IP / access code needed)

Works as long as the printer is cloud-connected (`online: true`).

1. Log in (accounts usually have e-mail 2FA):
```bash
curl -s -X POST https://api.bambulab.com/v1/user-service/user/login \
  -H "Content-Type: application/json" \
  -d '{"account":"<EMAIL>","password":"<PASSWORD>"}'   # -> loginType "verifyCode"
# ask the user for the e-mailed code, then repeat with "code":"<6 digits>"  -> accessToken (~3 months)
```
2. Devices and user id:
```bash
curl -s https://api.bambulab.com/v1/iot-service/api/user/bind -H "Authorization: Bearer $TOKEN"              # dev_id, dev_access_code, name
curl -s https://api.bambulab.com/v1/design-user-service/my/preference -H "Authorization: Bearer $TOKEN"     # uid
```
3. Connect with paho-mqtt: broker `us.mqtt.bambulab.com:8883` (TLS), username `u_<uid>`, password = accessToken.
   Topics: `device/<serial>/report` (status) and `device/<serial>/request` (commands).
   Ask for a full state dump: `{"pushing":{"sequence_id":"0","command":"pushall"}}`.
4. Everything in the report lives under `print.*` (`print.gcode_state`, `print.nozzle_temper`, `print.mc_percent`, `print.hms`), not at top level.

Store the token outside the skill folder (e.g. `~/.config/bambu/config.json`, mode 600). Never commit it.

## Option B: Local MQTT (LAN mode)

Broker `<printer-ip>:8883`, username `bblp`, password = LAN access code (printer display), TLS with `cert_reqs=ssl.CERT_NONE` + `tls_insecure_set(True)`. Same topics as above.

## Pitfall: command signature on newer firmware (>= ~01.07)

Newer firmware requires **signed MQTT commands**. Unsigned control commands are rejected with HMS `0500_0500_0001_0007` ("MQTT command verification failed", code 65543).
Reading (status, `pushall`, `get_version`) keeps working; **only control commands are blocked**. Home Assistant's Bambu integration is affected too (`print_fun.mqtt_signature_required`).

Fix: on the printer enable **LAN-only mode + Developer mode**. Then unsigned commands over **local** MQTT are accepted again. Trade-off: cloud features (remote control via Bambu Handy) are gone.

## Useful commands (publish to `device/<serial>/request`)

```json
{"print": {"command": "pause",  "sequence_id": "1"}}
{"print": {"command": "resume", "sequence_id": "1"}}
{"print": {"command": "stop",   "sequence_id": "1"}}
{"print": {"command": "print_speed", "param": "2", "sequence_id": "1"}}
{"print": {"command": "gcode_line", "param": "M140 S60\n", "sequence_id": "1"}}
```
Speed levels: 1 silent, 2 standard, 3 sport, 4 ludicrous.

Load filament from AMS (only works if the printer is not stuck in `FINISH`; confirm on the display first):
```json
{"print": {"command": "ams_change_filament", "ams_id": 0, "slot_id": 0, "target": 0, "curr_temp": 0, "tar_temp": 250, "sequence_id": "<timestamp>"}}
```

## Verification
After sending a command, re-request `pushall` and check that `print.gcode_state` / `print.hms` changed as expected. A publish without error does not prove the printer accepted it (see signature pitfall).
