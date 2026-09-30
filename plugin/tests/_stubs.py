"""Cross-platform stand-ins for CLIs such as `claude` (ADR-0019).

A `#!/bin/sh` script named `claude` is found on PATH on POSIX only; Windows
finds programs by PATHEXT (`claude.cmd`) and cannot run a shebang. These
stubs are Python programs behind a launcher each OS can run from PATH.
"""
from __future__ import annotations

import os
import pathlib
import stat
import sys


def make_python_stub(directory: pathlib.Path, name: str, body: str) -> pathlib.Path:
    """Put an executable `name` on *directory* that runs Python *body*.

    *body* sees ``sys.argv[1:]`` as the stub's own arguments. Returns the path
    that ``shutil.which(name)`` resolves to.
    """
    directory = pathlib.Path(directory)
    script = directory / ("_%s_stub.py" % name)
    script.write_text(body, encoding="utf-8")
    if os.name == "nt":
        launcher = directory / (name + ".cmd")
        launcher.write_text(
            '@echo off\r\n"%s" "%s" %%*\r\nexit /b %%ERRORLEVEL%%\r\n' % (sys.executable, script),
            encoding="utf-8",
        )
    else:
        launcher = directory / name
        launcher.write_text(
            '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, script), encoding="utf-8"
        )
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return launcher


def echo_stub_body(text: str, exit_code: int = 0, sleep: float = 0,
                   read_stdin: bool = False, echo_args: bool = False) -> str:
    """Python body: optionally drain stdin, sleep, print, exit."""
    return (
        "import sys, time\n"
        "if %r:\n    sys.stdin.read()\n"
        "time.sleep(%r)\n"
        "print(' '.join(sys.argv[1:]) if %r else %r)\n"
        "sys.exit(%d)\n"
    ) % (read_stdin, float(sleep), echo_args, text, exit_code)
