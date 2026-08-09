# Changelog

## 0.1.9

- Fix structured NRI capability parsing for live Pioneer parser output (`device` container, `@text` scalars, `@attributes` collections).
- Apply receiver-provided Main zone `volmax` as volume reference and refresh volume/source state when NRI arrives after MVL/SLI.

## 0.1.8

- Decimal MVL absolute volume model with NRI `volmax` reference.
- Initial structured NRI capabilities, dynamic inputs/listening modes, IFV positional-only parsing.
