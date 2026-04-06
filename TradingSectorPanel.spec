# -*- mode: python ; coding: utf-8 -*-

common_datas = [
    ('data/tickers.csv', 'data'),
]
common_hiddenimports = ['core.market_data', 'desktop.runtime', 'scraper.scrape_rankings']

panel_analysis = Analysis(
    ['desktop\\panel_app.py'],
    pathex=[],
    binaries=[],
    datas=common_datas,
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
panel_pyz = PYZ(panel_analysis.pure)
panel_exe = EXE(
    panel_pyz,
    panel_analysis.scripts,
    [],
    exclude_binaries=True,
    name='TradingSectorPanel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

host_analysis = Analysis(
    ['desktop\\native_host.py'],
    pathex=[],
    binaries=[],
    datas=common_datas,
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
host_pyz = PYZ(host_analysis.pure)
host_exe = EXE(
    host_pyz,
    host_analysis.scripts,
    [],
    exclude_binaries=True,
    name='TradingSectorNativeHost',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    panel_exe,
    host_exe,
    panel_analysis.binaries,
    panel_analysis.datas,
    host_analysis.binaries,
    host_analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TradingSectorPanel',
)
