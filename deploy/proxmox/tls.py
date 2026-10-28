"""Generate a private installation CA and a server certificate without disabling TLS checks."""
import argparse
import ipaddress
import os
import re
import subprocess
from pathlib import Path


def generate(directory, hostname, address, crl_url=None):
    address = ipaddress.IPv4Address(address)
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", hostname):
        raise ValueError("Invalid TLS hostname")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    previous = os.umask(0o077)
    try:
        extensions = directory / "server.ext"
        alternative_names = f"IP:{address}"
        if hostname != str(address):
            alternative_names += f",DNS:{hostname}"
        extensions.write_text("basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                              "extendedKeyUsage=serverAuth\nsubjectAltName=" + alternative_names + "\n" +
                              ("crlDistributionPoints=URI:" + crl_url + "\n" if crl_url else ""), encoding="ascii")
        (directory / "index.txt").write_text("", encoding="ascii")
        (directory / "crlnumber").write_text("01\n", encoding="ascii")
        (directory / "ca.cnf").write_text("[ca]\ndefault_ca=authority\n[authority]\ndatabase=index.txt\nprivate_key=ca.key\n"
                                        "certificate=ca.crt\ncrlnumber=crlnumber\ndefault_md=sha256\ndefault_crl_days=7\n", encoding="ascii")
        commands = [
            ["req", "-x509", "-newkey", "rsa:3072", "-nodes", "-sha256", "-days", "3650", "-subj", "/CN=PC MED private installation CA",
             "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
             "-keyout", "ca.key", "-out", "ca.crt"],
            ["req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256", "-subj", f"/CN={hostname}", "-keyout", "server.key", "-out", "server.csr"],
            ["x509", "-req", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial", "-days", "397",
             "-sha256", "-extfile", "server.ext", "-out", "server.crt"],
            ["verify", "-purpose", "sslserver", "-CAfile", "ca.crt", "server.crt"],
            ["ca", "-gencrl", "-batch", "-config", "ca.cnf", "-out", "ca-crl.pem"],
            ["crl", "-in", "ca-crl.pem", "-outform", "DER", "-out", "ca.crl"],
        ]
        for arguments in commands:
            subprocess.run(["openssl", *arguments], cwd=directory, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    finally:
        os.umask(previous)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--crl-url")
    options = parser.parse_args()
    generate(options.directory, options.hostname, options.address, options.crl_url)
