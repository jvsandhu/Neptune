"""Authenticated loopback IPC to the C++ helper in the game's Proton prefix."""
import hmac
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import threading
import time

MAX_FRAME = 20 * 1024 * 1024

class BridgeError(RuntimeError):
    pass


def receive_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise BridgeError('Proton helper disconnected. Any tracked patches are being restored.')
        data.extend(chunk)
    return bytes(data)


def receive_frame(sock):
    size, = struct.unpack('<I', receive_exact(sock, 4))
    if size > MAX_FRAME:
        raise BridgeError('Proton helper sent an oversized message.')
    return receive_exact(sock, size).decode('utf-8')


def send_frame(sock, text):
    data = text.encode('utf-8')
    if len(data) > MAX_FRAME:
        raise BridgeError('Message exceeds the bridge limit.')
    sock.sendall(struct.pack('<I', len(data)) + data)


class Bridge:
    def __init__(self, connection, process=None, log=None):
        self.connection = connection
        self.process = process
        self.log = log
        self.lock = threading.RLock()
        self.closed = False

    @classmethod
    def start(cls, helper, appid='2483190', timeout=45):
        if os.geteuid() == 0:
            raise BridgeError('Run Luna as your regular Steam user, without sudo.')
        executable = shutil.which('protontricks-launch')
        if not executable:
            raise BridgeError('Install protontricks: sudo pacman -Syu protontricks')
        helper = Path(helper).resolve()
        if not helper.is_file():
            raise BridgeError('C++ helper is missing. Build the native package first.')
        if not appid.isascii() or not appid.isdecimal() or int(appid) <= 0:
            raise BridgeError('Steam App ID must be a positive number.')
        log_dir = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'neptune-native'
        log_dir.mkdir(parents=True, exist_ok=True)
        log = (log_dir / 'proton.log').open('w')
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        token = secrets.token_hex(32)
        process = None
        try:
            process = subprocess.Popen([executable, '--appid', appid, str(helper),
                                        str(listener.getsockname()[1]), token],
                                       cwd=helper.parent, stdout=log, stderr=log)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                listener.settimeout(min(1, max(0.01, deadline - time.monotonic())))
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    if process.poll() is not None and process.returncode != 0:
                        raise BridgeError(f'Proton helper failed. See {log_dir / "proton.log"}')
                    continue
                connection.settimeout(min(2, max(0.01, deadline-time.monotonic())))
                try:
                    hello = receive_frame(connection)
                    if not hmac.compare_digest(hello, 'LUNA1 ' + token):
                        connection.close()
                        continue
                except (OSError, BridgeError, UnicodeError):
                    connection.close()
                    continue
                connection.settimeout(30)
                return cls(connection, process, log)
            raise BridgeError(f'Proton helper did not connect. Check {log_dir / "proton.log"}')
        except Exception:
            if process is not None and process.poll() is None:
                process.terminate()
            log.close()
            raise
        finally:
            listener.close()

    def call(self, operation, *arguments):
        with self.lock:
            if self.closed:
                raise BridgeError('The connection is closed. Reconnect to continue.')
            try:
                send_frame(self.connection, ' '.join([operation, *(str(arg) for arg in arguments)]))
                response = receive_frame(self.connection)
            except (OSError, UnicodeError, BridgeError) as error:
                # After a timeout, never consume a late response as the next request.
                self.abort()
                raise BridgeError(f'Connection lost; operation completion may be uncertain: {error}') from error
            if response.startswith('ERR '):
                raise BridgeError(response[4:])
            if not response.startswith('OK '):
                self.abort()
                raise BridgeError('Invalid bridge response; disconnected.')
            return response[3:]

    def read(self, address, size):
        return bytes.fromhex(self.call('READ', f'{address:x}', size))

    def write(self, address, value):
        self.call('WRITE', f'{address:x}', bytes(value).hex())

    def patch(self, address, expected, value):
        self.call('PATCH', f'{address:x}', bytes(expected).hex(), bytes(value).hex())

    def abort(self):
        with self.lock:
            self.closed = True
            self.connection.close()
            if self.log:
                self.log.close()

    def close(self):
        with self.lock:
            if self.closed:
                return
            # A restore failure stays visible and keeps the connection for retry.
            self.call('CLOSE')
            self.abort()
