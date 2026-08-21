"""HUD + iPhone talk. HTTPS on all interfaces (Safari needs HTTPS for the mic).

On a PC hotspot the phone usually reaches https://192.168.137.1:8791/phone
"""
from __future__ import annotations

import json
import queue
import socket
import ssl
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HUD_DIR = Path(__file__).resolve().parent / "hud"
CERT_DIR = Path(__file__).resolve().parent / "certs"
PORT = 8791

_state = {"state": "idle", "level": 0.0, "line": "", "name": "J.A.R.V.I.S."}
_lock = threading.Lock()
_httpd: ThreadingHTTPServer | None = None
incoming_jobs: queue.Queue = queue.Queue()


class UtteranceJob:
    def __init__(self, data: bytes, content_type: str):
        self.data = data
        self.content_type = content_type
        self.event = threading.Event()
        self.mp3 = b""
        self.text = ""
        self.error = ""

    def finish(self, text: str = "", mp3: bytes = b"", error: str = "") -> None:
        self.text = text
        self.mp3 = mp3
        self.error = error
        self.event.set()


def set_state(state: str, line: str = "", level: float = 0.0) -> None:
    with _lock:
        _state["state"] = state
        _state["line"] = (line or "")[:80]
        _state["level"] = float(level)


def lan_ips() -> list[str]:
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127.") and ip not in found:
            found.append(ip)
    except OSError:
        pass
    # Windows Mobile Hotspot / ICS default
    if "192.168.137.1" not in found:
        found.append("192.168.137.1")
    return found


def _ensure_cert(ips: list[str]) -> tuple[Path, Path] | None:
    CERT_DIR.mkdir(exist_ok=True)
    cert = CERT_DIR / "jarvis.pem"
    key = CERT_DIR / "jarvis-key.pem"
    stamp = CERT_DIR / "ips.txt"
    wanted = ",".join(["127.0.0.1", "localhost", *ips])
    if cert.is_file() and key.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8") == wanted:
        return cert, key
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import datetime
        import ipaddress
    except ImportError:
        print("[hud] pip install cryptography  (needed for iPhone HTTPS/mic)", flush=True)
        return None

    pkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    names = [x509.DNSName("localhost"), x509.DNSName("jarvis.local")]
    names.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    for ip in ips:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            names.append(x509.DNSName(ip))
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis")]) )
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jarvis")]))
        .public_key(pkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
    )
    crt = builder.sign(pkey, hashes.SHA256())
    key.write_bytes(
        pkey.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
    stamp.write_text(wanted, encoding="utf-8")
    return cert, key


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/state":
            with _lock:
                body = json.dumps(_state).encode()
            self._send(body, "application/json")
            return
        if path in ("/", "/index.html"):
            target = HUD_DIR / "index.html"
        elif path in ("/phone", "/phone.html"):
            target = HUD_DIR / "phone.html"
        else:
            target = (HUD_DIR / path.lstrip("/")).resolve()
            if HUD_DIR not in target.parents and target != HUD_DIR:
                self._send(b"not found", "text/plain", 404)
                return
        if not target.is_file():
            self._send(b"not found", "text/plain", 404)
            return
        ctype = "text/html" if target.suffix in (".html", "") else "application/octet-stream"
        if target.suffix == ".html":
            ctype = "text/html"
        self._send(target.read_bytes(), ctype)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path != "/utterance":
            self._send(b"not found", "text/plain", 404)
            return
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n <= 0 or n > 12_000_000:
            self._send(b"bad size", "text/plain", 400)
            return
        data = self.rfile.read(n)
        job = UtteranceJob(data, self.headers.get("Content-Type", "application/octet-stream"))
        incoming_jobs.put(job)
        if not job.event.wait(120):
            self._send(b'{"error":"timeout"}', "application/json", 504)
            return
        if job.error:
            self._send(json.dumps({"error": job.error, "text": job.text}).encode(), "application/json", 500)
            return
        if job.mp3:
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Jarvis-Text", job.text[:200].encode("latin-1", "replace").decode("latin-1"))
            self.send_header("Content-Length", str(len(job.mp3)))
            self.end_headers()
            self.wfile.write(job.mp3)
            return
        self._send(json.dumps({"text": job.text, "reply": "ok"}).encode(), "application/json")

    def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a) -> None:
        pass


def _try_firewall(port: int) -> None:
    subprocess.run(
        [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            "name=Jarvis HUD",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={port}",
            "profile=private,domain,public",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def start_hud(open_browser: bool = True) -> None:
    global _httpd
    ips = lan_ips()
    pair = _ensure_cert(ips)
    _httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    _httpd.allow_reuse_address = True
    scheme = "http"
    if pair:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(pair[0]), str(pair[1]))
        _httpd.socket = ctx.wrap_socket(_httpd.socket, server_side=True)
        scheme = "https"
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    _try_firewall(PORT)
    local = f"{scheme}://127.0.0.1:{PORT}/"
    print(f"[hud] PC:     {local}  (F fullscreen)", flush=True)
    print("[hud] iPhone: join the PC's Wi-Fi hotspot, then Safari:", flush=True)
    for ip in ips:
        print(f"         {scheme}://{ip}:{PORT}/phone", flush=True)
    print("[hud] Safari will warn about the certificate — tap Advanced, then Visit this website.", flush=True)
    print("[hud] Allow microphone when asked. Hold the gold button to talk.", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(local)).start()


def stop_hud() -> None:
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd = None
