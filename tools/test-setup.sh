#!/bin/bash

mkdir ca
openssl req -new -nodes -x509 -days 3650 -extensions v3_ca -keyout ca/ca.key -out ca/ca.crt -subj "/CN=ca"
openssl genrsa -out ca/server.key 2048
openssl req -out ca/server.csr -key ca/server.key -new -nodes -subj "/CN=server"
openssl x509 -req -in ca/server.csr -CA ca/ca.crt -CAkey ca/ca.key -CAcreateserial -out ca/server.crt -days 3650
chmod -R a+r ca/*

docker compose up -d
