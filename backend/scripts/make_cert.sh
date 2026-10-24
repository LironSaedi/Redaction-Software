#!/bin/sh
# Create a private certificate authority and a TLS certificate for an on-prem Obscura server.
#
#   scripts/make_cert.sh redact.office.lan 192.168.1.50      # names / IPs staff will type in the browser
#
# Writes data/tls/: ca.crt (install this on staff computers once, as a trusted root), server.crt, server.key.
# Then start the server with:
#   .venv/bin/python -m obscura.main --host 0.0.0.0 --cert data/tls/server.crt --key data/tls/server.key
#
# Nothing here contacts the internet. Keys never leave this machine; server.key and ca.key are mode 0600.
set -eu

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <hostname-or-ip> [more names / IPs ...]" >&2
    exit 2
fi
command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }

cd "$(dirname "$0")/.."
OUT="${OBSCURA_DATA:-data}/tls"
mkdir -p "$OUT"
chmod 700 "$OUT"
umask 077

# subjectAltName list: IPs become IP:, everything else DNS:
SAN=""
for name in "$@" localhost 127.0.0.1; do
    case "$name" in
        *[!0-9.]*) entry="DNS:$name" ;;
        *) entry="IP:$name" ;;
    esac
    case ",$SAN," in *",$entry,"*) continue ;; esac
    SAN="${SAN:+$SAN,}$entry"
done

if [ ! -f "$OUT/ca.key" ]; then
    echo "creating private CA (valid 10 years) ..."
    openssl genrsa -out "$OUT/ca.key" 4096 2>/dev/null
    openssl req -x509 -new -key "$OUT/ca.key" -sha256 -days 3650 -out "$OUT/ca.crt" \
        -subj "/CN=Obscura Private CA" \
        -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign"
else
    echo "re-using existing CA in $OUT"
fi

echo "creating server certificate for: $SAN"
openssl genrsa -out "$OUT/server.key" 2048 2>/dev/null
openssl req -new -key "$OUT/server.key" -out "$OUT/server.csr" -subj "/CN=$1"
cat > "$OUT/server.ext" <<EOF
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$SAN
EOF
# 825 days is the longest validity browsers accept for a server certificate
openssl x509 -req -in "$OUT/server.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" -CAcreateserial \
    -out "$OUT/server.crt" -days 825 -sha256 -extfile "$OUT/server.ext" 2>/dev/null
rm -f "$OUT/server.csr" "$OUT/server.ext"
chmod 600 "$OUT/server.key" "$OUT/ca.key"
chmod 644 "$OUT/server.crt" "$OUT/ca.crt"

echo
echo "done:"
echo "  $OUT/ca.crt      -> install on each staff computer as a trusted root certificate (once)"
echo "  $OUT/server.crt  -> --cert"
echo "  $OUT/server.key  -> --key   (keep private)"
echo "  $OUT/ca.key      -> keep offline / backed up; needed only to issue a new server certificate"
