"""Server TLS policy: certificates required beyond loopback."""
import ipaddress
import os
import ssl


def server_context(host):
    certificate = os.environ.get('NODYS_TLS_CERT')
    key = os.environ.get('NODYS_TLS_KEY')
    if bool(certificate) != bool(key):
        raise ValueError('Set both NODYS_TLS_CERT and NODYS_TLS_KEY')
    if certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate,key)
        return context
    try: local = host == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError: local = False
    if not local:
        raise ValueError('A public control listener requires a TLS certificate and key')
    return None
