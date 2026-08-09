# Changelog

## 0.1.14

- Separate listening mode from IFA audio output format; remove IFA fallback for `listening_mode`.
- Match enabled NRI command codes to select/current display (e.g. LMD11 → Pure Direct while IFA reports Dolby Digital).
- Request LMD/IFA state after listening-mode commands for authoritative receiver confirmation.

## 0.1.13

- Fix listening-mode select entity: reconcile exact receiver state to NRI command-family options so HA no longer shows Unknown when state labels differ (e.g. Auto Surround → Auto/Direct).

## 0.1.12

- Improve listening-mode display: layered LMD protocol mapping with IFA `output_format` fallback for unknown codes; raw `listening_mode_code` retained separately from NRI selectable command options.

## 0.1.11

- Remove `return` control flow from read-loop `finally` blocks (Python 3.14 `SyntaxWarning`); cleanup moved to `_finalize_read_loop()` with unchanged transport lifecycle behaviour.

## 0.1.10

- Add transport session IDs, lifecycle diagnostics, and guarded reconnect/connect behaviour.
- Distinguish receiver EOF from other read/close errors in logs; expose transport counters in integration diagnostics.
- Start the read loop before post-connect startup queries so responses are consumed during reconnect refresh.

## 0.1.9

- Fix structured NRI capability parsing for live Pioneer parser output (`device` container, `@text` scalars, `@attributes` collections).
- Apply receiver-provided Main zone `volmax` as volume reference and refresh volume/source state when NRI arrives after MVL/SLI.

## 0.1.8

- Decimal MVL absolute volume model with NRI `volmax` reference.
- Initial structured NRI capabilities, dynamic inputs/listening modes, IFV positional-only parsing.
