# This file prevents the local supabase/ migrations directory from shadowing
# the installed supabase Python package (Python 3 namespace package collision).
#
# It temporarily removes the project root from sys.path, imports the real
# installed package, then restores the path. All subsequent imports of
# `supabase` will use the cached real module from sys.modules.
import sys, os, importlib

sys.modules.pop(__name__, None)

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_saved = sys.path[:]
sys.path = [p for p in sys.path if p != _root]

try:
    _real = importlib.import_module(__name__)
    sys.modules[__name__] = _real
finally:
    sys.path = _saved
