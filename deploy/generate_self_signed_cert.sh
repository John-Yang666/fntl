#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT_DIR="${CERT_DIR:-$SCRIPT_DIR/certs}"
CERT_NAME="${CERT_NAME:-bt_nms}"
CA_NAME="${CA_NAME:-bt_nms_local_ca}"
CERT_HOSTS="${CERT_HOSTS:-localhost,127.0.0.1}"
CERT_DAYS="${CERT_DAYS:-825}"
CA_DAYS="${CA_DAYS:-3650}"

mkdir -p "$CERT_DIR"

cert_path="$CERT_DIR/$CERT_NAME.crt"
key_path="$CERT_DIR/$CERT_NAME.key"
csr_path="$CERT_DIR/$CERT_NAME.csr"
ca_cert_path="$CERT_DIR/$CA_NAME.crt"
ca_key_path="$CERT_DIR/$CA_NAME.key"
ca_config_path="$(mktemp)"
server_config_path="$(mktemp)"

cleanup() {
  rm -f "$ca_config_path" "$server_config_path" "$csr_path"
}
trap cleanup EXIT

cat > "$ca_config_path" <<EOF
[req]
default_bits = 2048
prompt = no
distinguished_name = dn
x509_extensions = ca_ext

[dn]
C = CN
ST = Local
L = Local
O = BT_NMS
OU = Local Development CA
CN = BT_NMS Local Development CA

[ca_ext]
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
EOF

if [ ! -f "$ca_cert_path" ] || [ ! -f "$ca_key_path" ]; then
  openssl req \
    -x509 \
    -nodes \
    -newkey rsa:2048 \
    -days "$CA_DAYS" \
    -sha256 \
    -keyout "$ca_key_path" \
    -out "$ca_cert_path" \
    -config "$ca_config_path"
fi

cat > "$server_config_path" <<EOF
[req]
default_bits = 2048
prompt = no
distinguished_name = dn
req_extensions = server_ext

[dn]
C = CN
ST = Local
L = Local
O = BT_NMS
OU = Local Development
CN = localhost

[server_ext]
basicConstraints = critical, CA:false
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
EOF

dns_index=1
ip_index=1
IFS=',' read -r -a hosts <<< "$CERT_HOSTS"
for raw_host in "${hosts[@]}"; do
  host="$(printf '%s' "$raw_host" | xargs)"
  if [ -z "$host" ]; then
    continue
  fi

  if [[ "$host" =~ ^[0-9]+(\.[0-9]+){3}$ || "$host" == *:* ]]; then
    echo "IP.$ip_index = $host" >> "$server_config_path"
    ip_index=$((ip_index + 1))
  else
    echo "DNS.$dns_index = $host" >> "$server_config_path"
    dns_index=$((dns_index + 1))
  fi
done

openssl req \
  -nodes \
  -newkey rsa:2048 \
  -sha256 \
  -keyout "$key_path" \
  -out "$csr_path" \
  -config "$server_config_path"

openssl x509 \
  -req \
  -in "$csr_path" \
  -CA "$ca_cert_path" \
  -CAkey "$ca_key_path" \
  -CAcreateserial \
  -days "$CERT_DAYS" \
  -sha256 \
  -out "$cert_path" \
  -extfile "$server_config_path" \
  -extensions server_ext

chmod 600 "$ca_key_path"
chmod 600 "$key_path"
chmod 644 "$ca_cert_path"
chmod 644 "$cert_path"

printf 'Local CA:     %s\n' "$ca_cert_path"
printf 'Certificate: %s\n' "$cert_path"
printf 'Private key:  %s\n' "$key_path"
printf 'SAN hosts:    %s\n' "$CERT_HOSTS"
