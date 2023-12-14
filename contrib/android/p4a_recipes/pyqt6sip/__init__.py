import os

from pythonforandroid.recipes.pyqt6sip import PyQt6SipRecipe
from pythonforandroid.util import load_source

util = load_source('util', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'util.py'))


assert PyQt6SipRecipe._version == "13.6.0"
assert PyQt6SipRecipe.depends == ['setuptools', 'python3']
assert PyQt6SipRecipe.python_depends == []


class PyQt6SipRecipePinned(util.InheritedRecipeMixin, PyQt6SipRecipe):
    sha512sum = "bd2fa70d64544d8104d3477cb650a0e6bcefa0008680afcf7d187ba3fb1117871c0237d3a7f047144c8a8a8eeb8da941a3b206f8ee0601cb2cc734243cdb9d46"


recipe = PyQt6SipRecipePinned()
