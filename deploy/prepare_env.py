"""Copy existing private configuration once; never replace an existing runtime.env."""
import argparse
import fcntl
import os
from pathlib import Path
import stat


def prepare(app_dir, data_dir):
    target = data_dir / 'runtime.env'
    if target.is_symlink():
        raise ValueError('Refusing a linked environment file.')
    if target.exists():
        if not target.is_file():
            raise ValueError('runtime.env must be a regular file.')
        return
    if (data_dir / '.connection-env-recovery.json').exists():
        raise ValueError('Complete the old environment recovery before migration.')
    source = app_dir / '.env'
    if not source.exists():
        source = app_dir / '.env.example'
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as original:
        if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
            raise ValueError('The source environment must be a regular file.')
        fcntl.flock(original, fcntl.LOCK_SH)
        content = original.read()
    # O_EXCL prevents a repeated/concurrent invocation from overwriting settings.
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise ValueError('Another environment migration completed; inspect its settings before continuing.') from None
    try:
        with os.fdopen(descriptor, 'wb') as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.app_dir, args.data_dir)
    except (OSError, ValueError):
        parser.exit(1, 'Environment migration refused. Check regular files, directory permissions and any pending environment recovery. Existing settings were retained.\n')
