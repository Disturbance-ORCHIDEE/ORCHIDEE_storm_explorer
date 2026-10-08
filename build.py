#!/usr/bin/env python3
"""Build the Storm Detection Explorer: data, then page. Any platform (no shell).
Usage: python build.py [--config storm_explorer_config.py] [build_data.py options, e.g. --only isimip --skip ddamage]
"""
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
cfg = [a for i, a in enumerate(args) if i > 0 and args[i - 1] == "--config"]
subprocess.run([sys.executable, os.path.join(HERE, "build_data.py")] + args, check=True)
subprocess.run([sys.executable, os.path.join(HERE, "assemble.py")] + (["--config", cfg[0]] if cfg else []), check=True)
