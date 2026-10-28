import subprocess
import sys
import textwrap


def test_worker_audit_allows_only_bound_loopback_and_target_writes(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    source = tmp_path / 'source' / '.vibelution'
    source.mkdir(parents=True)
    code = textwrap.dedent('''
        import os, socket, sys
        from pathlib import Path
        from scripts.assistant_reminder_offline_worker import _install_worker_audit
        root = Path(sys.argv[1]); port = 45123
        source_lock = root.parent / 'source/.vibelution/reminder-route-gate.lock'
        _install_worker_audit(root, port, route_lock_path=source_lock)
        (root / 'allowed').write_text('ok')
        source_lock.parent.mkdir(parents=True, exist_ok=True)
        source_lock.write_text('lock')
        try: (root.parent / 'outside').write_text('no')
        except PermissionError: pass
        else: raise AssertionError('outside write allowed')
        socket.getaddrinfo('127.0.0.1', port)
        try: socket.getaddrinfo('127.0.0.1', port + 1)
        except PermissionError: pass
        else: raise AssertionError('foreign port allowed')
        try: socket.socket().connect(('127.0.0.1', port + 1))
        except PermissionError: pass
        else: raise AssertionError('foreign connect allowed')
    ''')
    result = subprocess.run([sys.executable, '-B', '-c', code, str(target)], capture_output=True, text=True,
                            timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    assert (target / 'allowed').read_text() == 'ok' and not (tmp_path / 'outside').exists()
    assert (source / 'reminder-route-gate.lock').read_text() == 'lock'
