"""Fail-closed Linux worker isolation: Landlock filesystem + seccomp syscall allowlist."""

import ctypes
import errno
import os
import platform
import resource


class SandboxUnavailable(RuntimeError):
    pass


def limit_resources(memory_mb, cpu_seconds):
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def isolate(directory, memory_mb=1536, cpu_seconds=90):
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SandboxUnavailable("Workbook script isolation requires Linux x86_64 with Landlock.")
    limit_resources(memory_mb, cpu_seconds)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
        raise SandboxUnavailable("Workbook worker could not enable no-new-privileges.")
    abi = libc.syscall(444, 0, 0, 1)  # landlock_create_ruleset(VERSION)
    if abi < 3:
        raise SandboxUnavailable("Workbook worker requires Landlock ABI 3 or newer.")

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int)]

    # Handle all ABI-3 filesystem permissions, granting only job-local regular
    # files/directories. No executables, devices, symlinks, sockets or external paths.
    handled = (1 << 15) - 1
    allowed = sum(1 << bit for bit in (1, 2, 3, 4, 5, 7, 8, 13, 14))
    ruleset = Ruleset(handled)
    descriptor = libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0)
    if descriptor < 0:
        raise SandboxUnavailable("Workbook filesystem policy could not be created.")
    parent = os.open(directory, os.O_PATH | os.O_CLOEXEC)
    try:
        rule = PathRule(allowed, parent)
        if libc.syscall(445, descriptor, 1, ctypes.byref(rule), 0) or libc.syscall(446, descriptor, 0):
            raise SandboxUnavailable("Workbook filesystem policy could not be enforced.")
    finally:
        os.close(parent)
        os.close(descriptor)

    class Filter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort), ("filters", ctypes.POINTER(Filter))]

    # Only file/memory/time/signal operations needed by an already-started
    # Python/XlsxWriter process. No sockets, process creation, exec, ptrace, mounts
    # or alternate architectures. Filesystem opens remain constrained by Landlock.
    syscalls = (0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20,
                21, 24, 25, 28, 32, 33, 39, 60, 72, 74, 75, 77, 78, 79, 82, 83, 84, 87, 89,
                91, 102, 104, 107, 108, 110, 186, 202, 217, 228, 230, 231, 258, 262,
                263, 264, 267, 268, 269, 270, 271, 280, 292, 302, 316, 318, 332, 436, 439)
    filters = [Filter(0x20, 0, 0, 4), Filter(0x15, 1, 0, 0xC000003E), Filter(0x06, 0, 0, 0x80000000),
               Filter(0x20, 0, 0, 0)]
    for syscall in syscalls:
        filters.extend((Filter(0x15, 0, 1, syscall), Filter(0x06, 0, 0, 0x7FFF0000)))
    filters.append(Filter(0x06, 0, 0, 0x00050000 | errno.EPERM))
    array = (Filter * len(filters))(*filters)
    program = Program(len(filters), array)
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0):  # PR_SET_SECCOMP, FILTER
        raise SandboxUnavailable("Workbook syscall policy could not be enforced.")
