# KV Store gRPC Gotchas

## Verified Tool Inventory

**Available in task container:**
- `python3` (guaranteed - task runtime)
- `bash` builtins: `kill`, `echo`, `cat`, `grep`, `ls`
- `/proc` filesystem (always available in Linux)

**NOT available in task container (verified):**
- `ps` - command not found
- `pgrep` - command not found  
- `pkill` - command not found
- `ss` - command not found
- `netstat` - command not found
- `lsof` - command not found
- `fuser` - command not found
- `curl` - command not found

**Implication**: Use `/proc`-based process management and Python for any process/port inspection.

## Process Management Without External Tools

### Find processes by cmdline pattern
```python
import os

for pid in os.listdir('/proc'):
    if pid.isdigit():
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmdline = f.read()
                if b'pattern' in cmdline:
                    print(f"Found PID {pid}")
        except (FileNotFoundError, PermissionError):
            pass
```

### Kill processes by cmdline pattern
```python
import os, signal

for pid in os.listdir('/proc'):
    if pid.isdigit():
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                if b'server.py' in f.read():
                    os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, FileNotFoundError):
            pass
```

### Check port listeners via /proc/net/tcp
Port 5328 = 0x14D0 in hex. Look for `:14D0` in /proc/net/tcp:
```bash
grep -i ':14D0 ' /proc/net/tcp /proc/net/tcp6 2>/dev/null
```

But prefer semantic checks: `grpc.channel_ready_future()` is more reliable.

## Thread Safety

**Problem**: gRPC dispatches each RPC on a thread pool thread. Handlers run concurrently.

**Solution**: Always guard state with `threading.Lock()`:
```python
def Handler(self, request, context):
    with self._lock:
        # ... all state access
```

Even a simple dict read can race with a write. The GIL protects single operations,
but read-modify-write sequences (increment, conditional update) will corrupt state.

## Server Lifecycle

**Problem**: `python server.py` in shell exits when shell closes.

**Solution**: Use proper daemonization:
```bash
# First kill any existing server (using Python since pkill unavailable)
python3 - <<'EOF'
import os, signal
for pid in os.listdir('/proc'):
    if pid.isdigit():
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                if b'server.py' in f.read():
                    os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, FileNotFoundError):
            pass
EOF
sleep 1

# Then start new server detached
nohup setsid python3 server.py >server.log 2>&1 </dev/null &
```

- `setsid`: New session, detach from terminal
- `nohup`: Ignore SIGHUP
- `</dev/null`: stdin from /dev/null (prevents blocking)
- `>server.log`: Capture output for debugging

**Verification**: Check `server.log` if the port isn't responding.

## Missing Key Semantics

**Problem**: Delete must distinguish "key absent" from "key present with value 0".

**Wrong**:
```python
value = ns.pop(key, 0)  # Can't tell if key existed with value 0
return success, value
```

**Right**:
```python
if key in ns:
    value = ns.pop(key)
    return True, value
else:
    return False, 0
```

## Protobuf Naming

**Proto to Python module mapping**:
- `kv-store.proto` → `kv_store_pb2.py`, `kv_store_pb2_grpc.py`
- Non-alphanumeric → underscore
- Always check actual generated filenames with `ls`

**Import in generated code**:
```python
# In kv_store_pb2_grpc.py
import kv_store_pb2 as kv__store__pb2
```

## Port Binding

**Check failure**: `add_insecure_port` returns 0 on failure:
```python
if server.add_insecure_port("[::]:5328") == 0:
    raise SystemExit("bind failed")
```

## Readiness vs Sleep

**Wrong**:
```python
import time; time.sleep(1)  # Might not be enough, or too long
```

**Right**:
```python
grpc.channel_ready_future(channel).result(timeout=10)
```

## int32 Range

Setting a protobuf int32 field to an out-of-range Python int raises `ValueError`
at serialization time. The RPC fails with UNKNOWN status.

For large aggregates, consider:
- Clamping values
- Using int64 in proto (if task allows)
- Handling overflow explicitly

## State Structure

**Namespace isolation**:
```python
self._store = defaultdict(dict)  # {namespace: {key: value}}
```

NOT:
```python
self._store = {}  # Loses namespace isolation
```

## Rule: Verify Environment Assumptions

Any command added to this skill was either:
1. Executed in `/app` and verified to work, OR
2. Derived from first principles (Python stdlib, /proc, bash builtins)

Never assume external tools exist in minimal containers.
