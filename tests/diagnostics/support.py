from __future__ import annotations
import runpy
from pathlib import Path
from types import SimpleNamespace

def load_script(path: Path):
    """Load a standalone diagnostics script without executing its __main__ block."""
    return SimpleNamespace(**runpy.run_path(str(path), run_name='mreader_diagnostics_test_module'))
