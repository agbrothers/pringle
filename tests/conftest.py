"""
Pytest session configuration.

BUG-037 workaround: Python 3.13 introduced incremental GC, which can fire at
any instruction boundary — including inside cffi/wgpu C-extension calls. The
wgpu-native poller thread holds GPU resources that the main-thread GC cycle
also touches, causing a fatal SIGABRT inside wgpu_native.

Disabling automatic collection at session start prevents the race. Explicit
gc.collect() calls still work, so objects are reclaimed; only the automatic
in-flight triggers are suppressed. Remove this when wgpu upstream resolves
the threading issue (tracked in BUG-037).
"""

import gc
import sys


if sys.version_info >= (3, 13):
    gc.disable()
