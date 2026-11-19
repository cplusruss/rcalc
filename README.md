# rcalc

A desktop calculator for RF and electronics engineers on Windows. Tabs of live calculators cover RF power, noise, VSWR and matching, a Smith chart that loads Touchstone files, transmission lines, cavities and waveguides, antennas, link budgets, radar, mixers, DSP, component networks, resistor values, capacitor self-resonance, PCB layout and thermal checks, unit conversions, physics, TI linear regulators, and reference tables (periodic table, mechanical data, galvanic corrosion). Type in any field and the related fields recompute at once; `Ctrl+Space` opens a finder that jumps to any field in any tab.

The app is a single portable `rcalc.exe`. It keeps its settings in `rcalc.json` beside the exe, and the capacitor self-resonance tab reads manufacturer s-parameter files from `resource\capacitors\` beside the exe.

## Build from source

Requires Windows and Python 3.13.

```powershell
pip install -r requirements.txt
build_exe.bat
```

The build writes `dist\rcalc.exe`. To run from source instead: `python rcalc.py`.
