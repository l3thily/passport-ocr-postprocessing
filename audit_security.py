"""Run only inside sandbox-exec. Uses a caller-created harmless canary."""
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

def denied(operation):
    try:
        operation()
    except OSError as error:
        assert error.errno in (errno.EPERM,errno.EACCES),repr(error)
        return True
    raise AssertionError('operation unexpectedly permitted')

def read_zero(path):
    with open(path,'rb') as stream:
        stream.read(0)

def connect(family,address):
    with socket.socket(family,socket.SOCK_STREAM) as channel:
        channel.settimeout(1)
        channel.connect(address)

canary=Path(sys.argv[1])
checks={}
checks['outside_read']=denied(lambda:read_zero(canary/'sentinel.txt'))
checks['outside_write']=denied(lambda:(canary/'unexpected.txt').write_text('probe'))
checks['downloads_read']=denied(lambda:read_zero('/Users/l3th/Downloads/drive-download-20261022T161601Z-1-001.zip'))
checks['home_directory_read']=denied(lambda:list(Path('/Users/l3th').iterdir()))
checks['system_configuration_read']=denied(lambda:list(Path('/private/etc').iterdir()))
checks['homebrew_configuration_read']=denied(lambda:list(Path('/opt/homebrew/etc').iterdir()))
link=Path('.tmp/outside-symlink')
link.unlink(missing_ok=True);link.symlink_to(canary/'sentinel.txt')
checks['symlink_escape']=denied(lambda:read_zero(link))
link.unlink()
checks['external_tcp']=denied(lambda:connect(socket.AF_INET,('1.1.1.1',443)))
checks['localhost_tcp']=denied(lambda:connect(socket.AF_INET,('127.0.0.1',9)))
checks['unix_socket']=denied(lambda:connect(socket.AF_UNIX,str(canary/'socket')))
code='''import errno,sys
try:
 with open(sys.argv[1],'rb') as f:f.read(0)
except OSError as e:
 sys.exit(0 if e.errno in (errno.EPERM,errno.EACCES) else 2)
sys.exit(1)
'''
child=subprocess.run([sys.executable,'-I','-S','-c',code,str(canary/'sentinel.txt')],capture_output=True)
assert child.returncode==0,(child.returncode,child.stderr)
checks['child_inherits_denial']=True
assert set(os.environ)<={'PATH','LANG','TZ','TMPDIR','LC_CTYPE'},'inherited environment'
checks['clean_environment']=True
assert sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment
checks['isolated_python_no_site']=True
Path('security_checks.json').write_text(json.dumps(checks,indent=2)+'\n')
print(json.dumps(checks))
