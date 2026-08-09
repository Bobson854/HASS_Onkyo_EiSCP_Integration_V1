# Pioneer eISCP for Home Assistant

A Home Assistant custom integration for newer Pioneer AV receivers that use the Onkyo/Pioneer **eISCP** network protocol (TCP, default port 60128).

Initial development and testing target the **Pioneer VSX-1131**. Newer Pioneer receivers adopted the same eISCP protocol used by Onkyo/Integra; other models may work but compatibility is **not yet guaranteed**.

> **Status:** Early development / experimental. API and entity set may change.

## Features

- Persistent eISCP TCP connection with reconnect handling
- Unsolicited receiver state updates (no aggressive polling)
- Main zone **media player**: power, volume, mute, input/source selection
- **IFA** audio-information parsing (input/output format, channels, sample rate)
- **IFV** video-information parser (defensive; field layout may vary by firmware)
- Summary **sensors** for audio input/output and connection status
- **Listening mode** select entity
- Architecture placeholders for HDMI output and Zone 2 (disabled by default)
- **Diagnostics** with full internal protocol state
- **`pioneer_eiscp.send_raw`** service for engineering and protocol testing
- DEBUG logging of TX/RX ISCP traffic

## Current status

| Area | Status |
|------|--------|
| Main zone media player | Working |
| IFA audio information | Working |
| IFV video information | Parser ready; limited entity exposure |
| Listening mode | Exact state on media player; select shows NRI command family (v0.1.13+) |
| Input sources | Dynamic from NRI when probed; static fallback before probe |
| Volume | Absolute decimal MVL with NRI `volmax` reference when available |
| HDMI output select | Placeholder (disabled by default) |
| Zone 2 | Capability detected from NRI; entities not implemented yet |
| HACS default store | Not submitted |
| NRI / dynamic discovery | Implemented via capability probe |

## Installation

### Manual

1. Copy the integration folder into your Home Assistant configuration:

   ```
   <config>/custom_components/pioneer_eiscp/
   ```

2. Restart Home Assistant.

3. Go to **Settings → Devices & Services → Add Integration** and search for **Pioneer eISCP**.

### HACS (custom repository)

This repository is structured for HACS custom-repository installation once published on GitHub with validation workflows passing. It is **not** in the default HACS store yet.

1. In HACS, open **Custom repositories**.
2. Add the repository URL and category **Integration**.
3. Install **Pioneer eISCP** from HACS and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Pioneer eISCP**.

Enter your receiver details in the setup form (no YAML or external config file is required):

| Field | Description |
|-------|-------------|
| **Host** | Receiver IP address or hostname (required; no default) |
| **Port** | eISCP TCP port (default `60128`) |
| **Name** | Friendly device name in Home Assistant |

Example host: `192.0.2.10` (replace with your receiver’s address).

During setup the integration sends a read-only **PWRQSTN** query to confirm the target responds as an eISCP receiver before creating the config entry.

To change host, port, or name later: **Settings → Devices & Services → Pioneer eISCP → Configure**.

Ensure **Network Control** (or equivalent IP control setting) is enabled on the AVR.

## Diagnostics / raw command testing

**Diagnostics:** Settings → Devices & Services → your receiver device → **Diagnostics** shows connection state, parsed IFA/IFV data, and raw command cache.

**Raw commands:** Developer Tools → Services:

```yaml
service: pioneer_eiscp.send_raw
data:
  iscp_command: IFAQSTN
```

Other useful queries: `IFVQSTN`, `LMDQSTN`, `PWRQSTN`.

## Capability probe (early development)

Run a **read-only** capability probe to capture what your receiver reports (including NRI XML) without creating new entities:

```yaml
service: pioneer_eiscp.probe_capabilities
```

In **Developer Tools → Actions**, use the **Receiver** dropdown when multiple AVRs exist, or leave it blank when only one receiver is configured. Do not use **Add target** (device/entity targeting is not supported for this action).

On success, Developer Tools shows a JSON response with `summary` and full `capability_probe` data. The same snapshot is also stored in device diagnostics.

The probe:

- sends read-only `QSTN` queries sequentially (PWR, MVL, AMT, SLI, LMD, IFA, IFV, NRI)
- correlates responses by 3-letter command prefix
- stores raw and parsed results in **diagnostics** under `capability_probe`
- does **not** automatically create Home Assistant entities from responses

Use this to improve model-specific support before hard-coding volume ranges, sources, or modes.

### Dynamic capabilities (NRI)

After a successful probe, supported receivers can expose **NRI** (Network Remote Information) data used internally for:

- input selectors (`selectorlist`)
- main-zone volume reference/range (`volmax`, `volstep`)
- listening-mode capabilities (`controllist`)
- receiver identity (model, firmware, serial)
- tone/control ranges and feature flags
- zone presence (for example Zone 2)

Entities use NRI-derived maps when available and fall back to static lists until the first successful probe. Device registry identifiers still use `host:port`; a future migration may adopt the receiver serial from NRI.

The **Listening Mode** select shows the closest NRI **command family** (e.g. Auto/Direct). The media player attribute `listening_mode` shows the **exact** decoder state (e.g. Auto Surround from IFA), with `listening_mode_code` retaining the raw LMD response.

See [CHANGELOG.md](CHANGELOG.md) for version notes (including transport lifecycle diagnostics in 0.1.10).

**Debug logging** (`configuration.yaml`):

```yaml
logger:
  logs:
    custom_components.pioneer_eiscp: debug
    custom_components.pioneer_eiscp.protocol.transport: debug
```

## Supported / tested hardware

| Model | Status |
|-------|--------|
| Pioneer VSX-1131 | Primary development target |

Other Pioneer eISCP models may work but are untested. Reports and PRs welcome via GitHub Issues.

## Development

### Requirements

- Python 3.11+ (matches current Home Assistant requirements)
- pytest (optional dev dependency)

### Run unit tests

```bash
pip install pytest
pytest
```

Or with the optional dev extra:

```bash
pip install -e ".[dev]"
pytest
```

Tests cover eISCP framing and IFA/IFV parsing without requiring a live receiver or Home Assistant instance.

### Repository validation

GitHub Actions run **HACS** and **hassfest** validation on push, pull request, and daily schedule.

### Brand assets

Custom integration branding (logo/icon) belongs in:

```
custom_components/pioneer_eiscp/brand/
```

No brand assets are included yet. Do not add copyrighted Pioneer/Onkyo logos without permission.

## License

MIT License — see [LICENSE](LICENSE). Copyright (c) 2026 Mark Jones.
