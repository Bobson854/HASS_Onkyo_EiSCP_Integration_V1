"""Synthetic NRI XML fixtures matching live parser output shape."""

from __future__ import annotations


def _selector_xml(code: str, name: str, *, enabled: bool = True) -> str:
    value = "1" if enabled else "0"
    return (
        f'    <selector id="{code}" name="{name}" value="{value}" '
        f'zone="1111" iconid="{int(code) if code.isdigit() else 0}"/>'
    )


# Fifteen enabled selectors including code 12 -> TV (generic test data).
_ENABLED_SELECTORS: tuple[tuple[str, str], ...] = (
    ("00", "Phono"),
    ("01", "CD"),
    ("02", "Tuner"),
    ("03", "BD"),
    ("04", "STRM BOX"),
    ("05", "HDMI 1"),
    ("06", "HDMI 2"),
    ("07", "HDMI 3"),
    ("08", "HDMI 4"),
    ("09", "HDMI 5"),
    ("10", "HDMI 6"),
    ("11", "HDMI 7"),
    ("12", "TV"),
    ("13", "USB"),
    ("14", "Bluetooth"),
)

SELECTOR_LINES = "\n".join(_selector_xml(code, name) for code, name in _ENABLED_SELECTORS)
DISABLED_SELECTOR = _selector_xml("99", "Disabled Input", enabled=False)

SYNTHETIC_NRI_XML = f"""<?xml version="1.0"?>
<response>
  <device>
    <brand>Pioneer</brand>
    <category>AV Receiver</category>
    <year>2016</year>
    <model>VSX-1131</model>
    <deviceserial>SYNTH00000001</deviceserial>
    <macaddress>00:AA:BB:CC:DD:EE</macaddress>
    <firmwareversion>9.9.9</firmwareversion>
    <zonelist>
      <zone id="1" value="1" name="Main" volmax="82" volstep="0.5"
            src="11111111" dst="00000000" lrselect="0"/>
      <zone id="2" value="1" name="Zone2"/>
    </zonelist>
    <selectorlist>
{SELECTOR_LINES}
{DISABLED_SELECTOR}
    </selectorlist>
    <controllist>
      <control id="LMD Pure Direct" value="1" code="11" zone="1" position="0"/>
      <control id="LMD Auto/Direct" value="1" code="AUTO" zone="1" position="0"/>
      <control id="LMD Stereo G" value="1" code="STEREO" zone="1" position="0"/>
      <control id="LMD Surround" value="1" code="SURR" zone="1" position="0"/>
      <control id="LMD Disabled Mode" value="0" code="OFF" zone="1" position="0"/>
      <control id="Bass" value="1" min="-10" max="10" step="1" zone="1"/>
      <control id="Treble" value="1" min="-10" max="10" step="1" zone="1"/>
      <control id="Center Level" value="1" min="-12" max="12" step="1" zone="1"/>
      <control id="Subwoofer Level" value="1" min="-15" max="12" step="1" zone="1"/>
    </controllist>
    <functionlist>
      <function id="DolbyAtmos" value="1"/>
      <function id="DTS:X" value="1"/>
      <function id="MCACC" value="1"/>
      <function id="Music Optimizer" value="1"/>
      <function id="AV Adjust" value="1"/>
    </functionlist>
    <netservicelist>
      <netservice id="1" name="Spotify" value="1"/>
      <netservice id="2" name="AirPlay" value="1"/>
    </netservicelist>
    <tuners>
      <tuner id="FM" name="FM" value="1" band="FM"/>
      <tuner id="AM" name="AM" value="1" band="AM"/>
    </tuners>
  </device>
</response>"""
