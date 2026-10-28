"""Fail installation unless HTTPS, the panel, OIDC/JWKS and API authentication work."""
import argparse
import json
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def probe(origin, context):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), NoRedirect())

    def fetch(path):
        request = urllib.request.Request(origin + path, headers={"Accept": "application/json"})
        with opener.open(request, timeout=5) as response:
            if response.url != origin + path or response.status != 200:
                raise ValueError("Unexpected redirect or HTTP status")
            body = response.read(1048577)
            if len(body) > 1048576:
                raise ValueError("Oversized verification response")
            return body

    discovery = json.loads(fetch("/realms/pcmed/.well-known/openid-configuration"))
    if discovery.get("issuer") != origin + "/realms/pcmed":
        raise ValueError("OIDC issuer differs from configured origin")
    keys = json.loads(fetch("/realms/pcmed/protocol/openid-connect/certs"))
    if not any(key.get("alg") == "RS256" for key in keys.get("keys", [])):
        raise ValueError("OIDC RS256 signing keys unavailable")
    if b"PC MED" not in fetch("/"):
        raise ValueError("Panel unavailable")
    try:
        fetch("/api/me")
    except urllib.error.HTTPError as error:
        if error.code == 401:
            return
        raise
    raise ValueError("Unauthenticated API request was not rejected")


def verify_crl(url, ca_file):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=5) as response:
        if response.url != url or response.status != 200:
            raise ValueError("CRL endpoint unavailable or redirected")
        body = response.read(1048577)
    if len(body) > 1048576:
        raise ValueError("Oversized CRL")
    with tempfile.TemporaryDirectory(prefix="pcmed-crl-check-") as temporary:
        filename = Path(temporary) / "ca.crl"
        filename.write_bytes(body)
        result = subprocess.run(["openssl", "crl", "-inform", "DER", "-in", str(filename), "-CAfile", str(ca_file), "-verify", "-noout", "-nextupdate"],
                                capture_output=True, text=True, check=True)
        if "verify OK" not in result.stderr or ssl.cert_time_to_seconds(result.stdout.strip().split("=", 1)[1]) <= time.time():
            raise ValueError("CRL signature or validity check failed")


def verify(origin, ca_file, timeout=240, crl_url=None):
    context = ssl.create_default_context(cafile=str(ca_file))
    deadline = time.monotonic() + timeout
    while True:
        try:
            probe(origin, context)
            if crl_url:
                verify_crl(crl_url, ca_file)
            print("PC MED verified: trusted HTTPS, panel, OIDC issuer/JWKS and authenticated API.")
            return
        except (OSError, ValueError, urllib.error.URLError, subprocess.CalledProcessError) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"PC MED readiness check failed: {error}") from error
            time.sleep(min(3, max(0, deadline - time.monotonic())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/opt/pcmed-rmm")
    parser.add_argument("--origin")
    parser.add_argument("--crl-url")
    parser.add_argument("--ca-file", default="/etc/pcmed/pki/trust.crt")
    parser.add_argument("--timeout", type=int, default=240)
    options = parser.parse_args()
    origin = options.origin
    if not origin:
        environment = dict(line.split("=", 1) for line in (Path(options.root) / ".env").read_text().splitlines() if "=" in line)
        origin = environment["PCMED_ORIGIN"]
        if environment.get("CRL_PORT"):
            options.crl_url = "http://" + environment["VPN_BIND_ADDRESS"] + ":" + environment["CRL_PORT"] + "/ca.crl"
    verify(origin, options.ca_file, options.timeout, options.crl_url)
