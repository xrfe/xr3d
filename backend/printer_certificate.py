"""Inspect and pin a Bambu LAN TLS certificate without sending credentials.

First inspect on a trusted LAN:
python -m backend.printer_certificate --host 192.168.1.20 --serial SERIAL
Then install only after independently checking the displayed SHA-256 fingerprint:
python -m backend.printer_certificate --host 192.168.1.20 --serial SERIAL --trust-sha256 HEX --directory printer-certs
"""
import argparse
import hashlib
import ipaddress
from pathlib import Path
import re
import socket
import ssl


def inspect_certificate(host):
    address = ipaddress.ip_address(host)
    if not any(address in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")):
        raise ValueError("Use the private IPv4 LAN address of the Bambu printer")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
    # Unauthenticated inspection only: no access code or MQTT packets are sent.
    with socket.create_connection((host,8883),10) as raw:
        with context.wrap_socket(raw,server_hostname=host) as connection:
            certificate=connection.getpeercert(binary_form=True)
    return certificate


def install(certificate, serial, fingerprint, directory):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}",serial): raise ValueError("Invalid printer serial number")
    expected=fingerprint.replace(":","").lower()
    if not re.fullmatch(r"[a-f0-9]{64}",expected) or hashlib.sha256(certificate).hexdigest()!=expected:
        raise ValueError("Certificate fingerprint does not match; nothing was trusted")
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/f"{serial}.pem"
    with target.open("x",encoding="ascii") as output: output.write(ssl.DER_cert_to_PEM_cert(certificate))
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host",required=True); parser.add_argument("--serial",required=True)
    parser.add_argument("--trust-sha256"); parser.add_argument("--directory",type=Path,default=Path("printer-certs"))
    args=parser.parse_args()
    certificate=inspect_certificate(args.host)
    print("Observed certificate SHA-256:",hashlib.sha256(certificate).hexdigest())
    if args.trust_sha256:
        target=install(certificate,args.serial,args.trust_sha256,args.directory)
        print("Trusted certificate saved:",target)
    else:
        print("No certificate installed. Verify the printer identity on a trusted LAN before trusting this fingerprint.")


if __name__=="__main__": main()
