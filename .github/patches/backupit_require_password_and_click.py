#!/usr/bin/env python3
"""Compatibility hook for older generator workflows.

BackupIT Ask + Pass uses RustDesk's native ``approve-mode = both`` behavior:
a valid password permits unattended access, while a remote user can approve a
request without the controller entering that password. No source patch is
required, and this hook intentionally makes no changes if a legacy workflow
still invokes it.
"""

import os
import sys


def main():
    enabled = os.environ.get("backupitRequirePasswordAndClick", "").strip().lower()
    if enabled == "true":
        print("BackupIT Ask + Pass uses native password-or-approval mode; no patch applied")
    else:
        print("BackupIT Ask + Pass patch skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
