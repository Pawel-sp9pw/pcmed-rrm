"""Renew the signed CRL daily, keeping the CA key outside the web server mount."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def refresh(directory=Path("/etc/pcmed/pki/issued"), public=Path("/opt/pcmed-rmm/secrets/pki-public")):
    previous = os.umask(0o077)
    try:
        subprocess.run(["openssl", "ca", "-gencrl", "-batch", "-config", "ca.cnf", "-out", "ca-crl.pem"], cwd=directory, check=True, capture_output=True)
        subprocess.run(["openssl", "crl", "-in", "ca-crl.pem", "-outform", "DER", "-out", "ca.crl"], cwd=directory, check=True, capture_output=True)
        descriptor, filename = tempfile.mkstemp(prefix=".crl-", dir=public)
        os.close(descriptor)
        temporary = Path(filename)
        try:
            shutil.copyfile(directory / "ca.crl", temporary)
            temporary.chmod(0o644)
            temporary.replace(public / "ca.crl")
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        os.umask(previous)


if __name__ == "__main__":
    refresh()
