# TLS Certificates

This directory is mounted read-only into the production Nginx containers.

Generate a local self-signed certificate:

```bash
./deploy/generate_self_signed_cert.sh
```

Include a deployment IP or domain in the certificate SAN list:

```bash
CERT_HOSTS=localhost,127.0.0.1,192.168.1.50,nms.example.com ./deploy/generate_self_signed_cert.sh
```

Nginx expects these server certificate files:

```text
deploy/certs/bt_nms.crt
deploy/certs/bt_nms.key
```

Trust this local CA certificate in macOS for browser access:

```text
deploy/certs/bt_nms_local_ca.crt
```

The generated certificates and private keys are ignored by Git. Replace the
server certificate and key with internal CA or public CA files using the same
names when deploying with trusted HTTPS.
