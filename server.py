#!/usr/bin/env python3
"""
Minimal HTTP server for h2 / h3.
Run on each server host before testing:
  mininet> h2 python3 server.py &
  mininet> h3 python3 server.py &
"""

import socket
import os

PORT = 80
HOST_IP = None

def get_my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.0.0.1', 1))
        return s.getsockname()[0]
    finally:
        s.close()

def handle(conn, addr, my_ip):
    try:
        conn.recv(4096)   # consume the HTTP request
        body = f"Hello from SERVER {my_ip}\n"
        resp = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Content-Type: text/plain\r\n"
            "Connection: close\r\n"
            "\r\n"
            + body
        )
        conn.sendall(resp.encode())
    finally:
        conn.close()

def main():
    my_ip = get_my_ip()
    print(f"[SERVER] {my_ip}:{PORT} ready")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', PORT))
    srv.listen(10)
    while True:
        conn, addr = srv.accept()
        print(f"[SERVER] {my_ip} ← connection from {addr[0]}")
        handle(conn, addr, my_ip)

if __name__ == '__main__':
    main()
