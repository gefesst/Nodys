"""TLS fixture excludes IP SANs so hostname mismatch remains testable."""
from tools.local_certificate import create_certificate as _create

def create_certificate(cert_path, key_path):
    _create(cert_path, key_path, include_ip=False)
