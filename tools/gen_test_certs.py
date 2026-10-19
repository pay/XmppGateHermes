#!/usr/bin/env python3
"""Generate a throwaway CA + server cert for the local XMPP test server.

Writes ca.pem (trust anchor), server.pem (leaf, SAN localhost + 127.0.0.1),
server.key (PKCS8). For a loopback connectivity test only.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

out = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
out.mkdir(parents=True, exist_ok=True)
now = dt.datetime.now(dt.timezone.utc)


def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def write(name: str, data: bytes) -> None:
    p = out / name
    p.write_bytes(data)
    print(f"wrote {p} ({len(data)} bytes)")


ca_key = key()
ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Hermes XMPP Test CA")])
ca_cert = (
    x509.CertificateBuilder()
    .subject_name(ca_name)
    .issuer_name(ca_name)
    .public_key(ca_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - dt.timedelta(days=1))
    .not_valid_after(now + dt.timedelta(days=30))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
    )
    .add_extension(
        x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False,
        ),
        critical=True,
    )
    .sign(ca_key, hashes.SHA256())
)

srv_key = key()
srv_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
srv_cert = (
    x509.CertificateBuilder()
    .subject_name(srv_name)
    .issuer_name(ca_name)
    .public_key(srv_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - dt.timedelta(days=1))
    .not_valid_after(now + dt.timedelta(days=30))
    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    .add_extension(
        x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
    )
    .add_extension(
        x509.SubjectKeyIdentifier.from_public_key(srv_key.public_key()), critical=False
    )
    .add_extension(
        x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False,
        ),
        critical=True,
    )
    .add_extension(
        x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
    )
    .add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]),
        critical=False,
    )
    .sign(ca_key, hashes.SHA256())
)

write("ca.pem", ca_cert.public_bytes(serialization.Encoding.PEM))
write("server.pem", srv_cert.public_bytes(serialization.Encoding.PEM))
write("ca+server.pem", ca_cert.public_bytes(serialization.Encoding.PEM) + srv_cert.public_bytes(serialization.Encoding.PEM))
write(
    "server.key",
    srv_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ),
)
