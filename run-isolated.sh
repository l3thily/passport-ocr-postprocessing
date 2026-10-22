#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON=${OCR_PYTHON:-/opt/homebrew/bin/python3}
mkdir -p "$ROOT/.tmp"
/usr/bin/env -i PATH=/usr/bin:/bin:/opt/homebrew/bin LANG=en_US.UTF-8 TZ=UTC TMPDIR="$ROOT/.tmp" "$PYTHON" -I -S - "$ROOT" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
profile='''(version 1)
(deny default)
(allow process-fork)
(allow process-exec)
(allow sysctl-read)
(allow file-read-metadata)
(allow mach-lookup (global-name "com.apple.system.logger") (global-name "com.apple.logd"))
(allow file-read* (literal "/") (subpath "/usr/lib") (subpath "/System") (subpath "/opt/homebrew/Cellar") (subpath "/Library/Apple") (subpath "/private/var/db/dyld") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random") (subpath "/dev/fd") (subpath PYTHON_BASE) (literal PYTHON_EXE) (subpath ROOT))
(allow file-write* (subpath ROOT) (literal "/dev/null"))
'''.replace('PYTHON_BASE',json.dumps(str(Path(sys.base_prefix).resolve()))).replace('PYTHON_EXE',json.dumps(str(Path(sys.executable).resolve()))).replace('ROOT',json.dumps(str(root)))
(root/'runtime.sb').write_text(profile)
PY
cd "$ROOT"
exec /usr/bin/env -i PATH=/usr/bin:/bin:/opt/homebrew/bin LANG=en_US.UTF-8 TZ=UTC TMPDIR="$ROOT/.tmp" \
  /usr/bin/sandbox-exec -f "$ROOT/runtime.sb" "$PYTHON" -I -S "$ROOT/postprocess.py" "$@"
