#!/usr/bin/env python3
"""
Compatibility entry point — the assistant is now CLAP (clap.py).

`python jarvis.py ...` keeps working for existing scripts and LaunchAgents.
"""

from clap import main

if __name__ == "__main__":
    main()
