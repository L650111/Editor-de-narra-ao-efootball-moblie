#!/usr/bin/env python3
"""Abre a interface ou o modo de terminal quando há argumentos."""
import sys

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--autoteste":
        from editor_cpk.diagnostics import verify_installation
        raise SystemExit(verify_installation(sys.argv[2]))
    if len(sys.argv) > 1:
        from editor_cpk.cli import main
    else:
        from editor_cpk.gui import main
    main()
