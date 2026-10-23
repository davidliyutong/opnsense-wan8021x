#!/bin/sh
# Test PKI for the EAP server: a trusted CA, a server certificate signed by it
# and an unrelated "rogue" CA used to exercise CA validation failures.
set -eu
d=$1
[ -f "$d/server.crt" ] && exit 0
mkdir -p "$d"
cd "$d"
subj() { echo "/C=XX/O=wan8021x test/CN=$1"; }
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "$(subj 'Test Root CA')" \
	-keyout ca.key -out ca.crt 2>/dev/null
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "$(subj 'Rogue Root CA')" \
	-keyout rogue-ca.key -out rogue-ca.crt 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "$(subj auth.example.test)" \
	-keyout server.key -out server.csr 2>/dev/null
printf 'subjectAltName=DNS:auth.example.test\nextendedKeyUsage=serverAuth\n' > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 3650 \
	-extfile server.ext -out server.crt 2>/dev/null
rm -f server.csr server.ext ca.srl
chmod 600 ./*.key
echo "generated test PKI in $d"
