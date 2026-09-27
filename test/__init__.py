import os
import sys

_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _parent in (_repo_root, os.path.join(_repo_root, 'albatross-python')):
  if _parent not in sys.path:
    sys.path.insert(0, _parent)
