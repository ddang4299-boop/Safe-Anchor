"""
tools/gen_lab_ca.py — Tạo CA tự ký cho phòng lab + chứng chỉ server, in SHA-256 để agent ghim.

    python tools/gen_lab_ca.py --ip 192.168.1.10 --dns ogk.local
    -> certs/ca.crt, certs/ca.key, certs/server.crt, certs/server.key
Chạy server TLS:  python -m server.main --host 0.0.0.0 --tls
Agent:           "ca_file": "certs/ca.crt", "pin_sha256": "<giá trị in ra>"
"""
import argparse
import datetime as dt
import hashlib
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(__file__).resolve().parent.parent / "certs"


def write_key(key, path: Path):
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", action="append", default=["127.0.0.1"])
    ap.add_argument("--dns", action="append", default=["localhost"])
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OGK Lab CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + dt.timedelta(days=825))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    srv_key = ec.generate_private_key(ec.SECP256R1())
    sans = [x509.DNSName(d) for d in a.dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in a.ip]
    srv = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, a.dns[-1])]))
           .issuer_name(ca_name).public_key(srv_key.public_key()).serial_number(x509.random_serial_number())
           .not_valid_before(now).not_valid_after(now + dt.timedelta(days=397))
           .add_extension(x509.SubjectAlternativeName(sans), critical=False)
           .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
           .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
           .sign(ca_key, hashes.SHA256()))
    write_key(ca_key, OUT / "ca.key")
    write_key(srv_key, OUT / "server.key")
    (OUT / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (OUT / "server.crt").write_bytes(srv.public_bytes(serialization.Encoding.PEM))
    pin = hashlib.sha256(srv.public_bytes(serialization.Encoding.DER)).hexdigest()
    print(f"Đã tạo CA + chứng chỉ server trong {OUT}")
    print(f"SAN: {a.dns} {a.ip}")
    print(f"pin_sha256 (dán vào config agent): {pin}")


if __name__ == "__main__":
    main()
