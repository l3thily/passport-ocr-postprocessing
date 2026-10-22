#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON=${OCR_PYTHON:-/opt/homebrew/bin/python3}
mkdir -p "$ROOT/.tmp"
"$PYTHON" -I - "$ROOT" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
profile='''(version 1)
(deny default)
(allow process*)
(allow sysctl-read)
(allow file-read-metadata)
(allow mach-lookup (global-name "com.apple.system.logger") (global-name "com.apple.logd"))
(allow file-read* (literal "/") (subpath "/usr") (subpath "/bin") (subpath "/System") (subpath "/opt/homebrew") (subpath "/Library/Apple") (subpath "/private/etc") (subpath "/private/var/db/dyld") (subpath "/dev") (subpath ROOT))
(allow file-write* (subpath ROOT) (literal "/dev/null"))
'''.replace('ROOT',json.dumps(str(root)))
(root/'runtime.sb').write_text(profile)
PY
cd "$ROOT"
exec /usr/bin/env -i PATH=/usr/bin:/bin:/opt/homebrew/bin LANG=en_US.UTF-8 TMPDIR="$ROOT/.tmp" \
  /usr/bin/sandbox-exec -f "$ROOT/runtime.sb" "$PYTHON" -I "$ROOT/postprocess.py" "$@"
