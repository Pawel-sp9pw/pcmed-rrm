"""Restrict Docker-published PC MED HTTPS without changing unrelated firewall rules."""
import argparse
import ipaddress
import json
import subprocess
from pathlib import Path


def rules(configuration):
    address = ipaddress.IPv4Address(configuration["address"])
    port = int(configuration["port"])
    networks = [ipaddress.IPv4Network(value, strict=True) for value in configuration["allowed_cidrs"]]
    if not address.is_private or address.is_loopback or address.is_unspecified or not 1024 <= port <= 49151 or not networks:
        raise ValueError("Private bind address, user port and explicit source CIDRs required")
    private = [ipaddress.IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    if any(not any(network.subnet_of(block) for block in private) for network in networks):
        raise ValueError("Only explicit private management/VPN source networks may be allowed")
    lines = ["*filter", ":PCMED-IN - [0:0]", "-F PCMED-IN"]
    ports = [port]
    if configuration.get("crl_port"):
        crl_port = int(configuration["crl_port"])
        if not 1024 <= crl_port <= 49151 or crl_port == port:
            raise ValueError("Invalid or colliding CRL port")
        ports.append(crl_port)
    for published_port in ports:
        match = f"-p tcp -m conntrack --ctorigdst {address} --ctorigdstport {published_port} --ctdir ORIGINAL"
        lines.extend(f"-A PCMED-IN {match} -s {network} -j RETURN" for network in networks)
        lines.append(f"-A PCMED-IN {match} -j DROP")
    lines.extend(["-A PCMED-IN -j RETURN", "COMMIT", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/pcmed/firewall.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    policy = rules(json.loads(Path(args.config).read_text(encoding="utf-8")))
    if args.check:
        print(policy)
        return
    subprocess.run(["/usr/sbin/iptables", "-w", "10", "-S", "DOCKER-USER"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["/usr/sbin/iptables-restore", "--wait", "10", "--noflush"], input=policy, text=True, check=True)
    jump = ["/usr/sbin/iptables", "-w", "10", "-C", "DOCKER-USER", "-j", "PCMED-IN"]
    if subprocess.run(jump, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        subprocess.run(["/usr/sbin/iptables", "-w", "10", "-I", "DOCKER-USER", "1", "-j", "PCMED-IN"], check=True)


if __name__ == "__main__":
    main()
