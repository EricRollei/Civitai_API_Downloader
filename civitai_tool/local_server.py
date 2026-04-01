"""
Local HTTP server for receiving URLs from the Chrome extension.
Runs on localhost:7865 by default.
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse


DEFAULT_PORT = 7865


class URLReceiverHandler(BaseHTTPRequestHandler):
    """HTTP request handler that receives URLs from the Chrome extension."""
    
    callback: Optional[Callable[[str], None]] = None
    
    def log_message(self, format: str, *args) -> None:
        """Suppress default logging."""
        pass
    
    def _send_cors_headers(self) -> None:
        """Send CORS headers to allow requests from any origin."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    
    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()
    
    def do_GET(self) -> None:
        """Handle GET requests - used for status check."""
        if self.path == "/status":
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {"status": "ok", "app": "Civitai Desktop Helper"}
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self) -> None:
        """Handle POST requests - receives URLs from extension."""
        if self.path == "/send-url":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(body)
                url = data.get("url", "")
                
                if url and self.callback:
                    # Call the callback with the URL
                    self.callback(url)
                
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "received", "url": url}
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                self.send_response(500)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                response = {"status": "error", "message": str(e)}
                self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()


class LocalURLServer:
    """Manages the local HTTP server for receiving URLs."""
    
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._running = False
        self._callback: Optional[Callable[[str], None]] = None
    
    def set_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback function to be called when a URL is received."""
        self._callback = callback
        URLReceiverHandler.callback = callback
    
    def start(self) -> bool:
        """Start the local server. Returns True if successful."""
        if self._running:
            return True
        
        try:
            # Create handler class with callback
            URLReceiverHandler.callback = self._callback
            
            self.server = HTTPServer(("127.0.0.1", self.port), URLReceiverHandler)
            self.thread = threading.Thread(target=self._run_server, daemon=True)
            self.thread.start()
            self._running = True
            return True
        except OSError as e:
            # Port might be in use
            print(f"Failed to start local server: {e}")
            return False
    
    def _run_server(self) -> None:
        """Run the server (called in a separate thread)."""
        if self.server:
            self.server.serve_forever()
    
    def stop(self) -> None:
        """Stop the local server."""
        if self.server:
            self.server.shutdown()
            self._running = False
    
    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running
