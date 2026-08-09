"""Synthetic NRI XML for tests (not from a live receiver)."""

SYNTHETIC_NRI_XML = """<?xml version="1.0"?>
<response>
  <device model="AVR-9000" brand="SynthBrand" deviceserial="SYNTH00000001"
          macaddress="00:AA:BB:CC:DD:EE" firmwareversion="9.9.9"
          year="2020" category="AV Receiver"/>
  <zonelist>
    <zone id="Main" value="1" name="Main" volmax="82" volstep="0.5"
          src="11111111" dst="00000000" lrselect="0"/>
    <zone id="Zone2" value="1" name="Zone 2"/>
  </zonelist>
  <selectorlist>
    <selector id="01" name="HDMI 1" value="1" zone="1111" iconid="1"/>
    <selector id="02" name="HDMI 2" value="0" zone="1111" iconid="2"/>
    <selector id="03" name="Tuner" value="1" zone="1111" iconid="3" addqueue="0"/>
  </selectorlist>
  <controllist>
    <control id="LMD Pure Direct" value="1" code="11"/>
    <control id="LMD Auto/Direct" value="1" code="AUTO"/>
    <control id="LMD Stereo G" value="1" code="STEREO"/>
    <control id="LMD Surround" value="1" code="SURR"/>
    <control id="LMD Disabled Mode" value="0" code="OFF"/>
    <control id="Bass" value="1" min="-10" max="10" step="1"/>
    <control id="Treble" value="1" min="-10" max="10" step="1"/>
    <control id="Center Level" value="1" min="-12" max="12" step="1"/>
    <control id="Subwoofer Level" value="1" min="-15" max="12" step="1"/>
  </controllist>
  <functionlist>
    <function id="DolbyAtmos" value="1"/>
    <function id="DTS:X" value="1"/>
    <function id="MCACC" value="1"/>
    <function id="Music Optimizer" value="1"/>
    <function id="AV Adjust" value="1"/>
  </functionlist>
</response>"""
