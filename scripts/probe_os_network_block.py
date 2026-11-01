"""Native socket probe of the dedicated interpreter, without the app audit hook.

Uses only TEST-NET documentation addresses, sends no personal data, imports no
business modules and reads no WeChat files. An immediate Windows 10013 proves
an OS access denial for this particular probe; timeouts are inconclusive.
"""
import json
import socket
import time

results = []
for label, family, address in [
    ("IPv4 TCP", socket.AF_INET, ("198.51.100.1", 443)),
    ("IPv6 TCP", socket.AF_INET6, ("2001:db8::1", 443)),
]:
    started = time.monotonic()
    with socket.socket(family, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        try:
            connection.connect(address)
        except OSError as error:
            code = getattr(error, "winerror", None) or error.errno
            state = "OS_ACCESS_DENIED" if code == 10013 else "INCONCLUSIVE_NETWORK_ERROR"
        else:
            code, state = 0, "UNEXPECTED_CONNECTION_SUCCEEDED"
        results.append({"probe": label, "state": state, "error_code": code,
                        "elapsed_ms": round((time.monotonic() - started) * 1000)})
print(json.dumps(results))
