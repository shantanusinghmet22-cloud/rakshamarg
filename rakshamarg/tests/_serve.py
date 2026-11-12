"""Serve docs/ over HTTP for browser tests (as GitHub Pages does); file:// pages cannot fetch the saved snapshot."""
import functools, http.server, socketserver, threading
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
def serve(directory):
    srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/index.html", srv
