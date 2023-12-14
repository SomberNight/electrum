import os

from pythonforandroid.recipes.pyqt6 import PyQt6Recipe
from pythonforandroid.util import load_source

util = load_source('util', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'util.py'))


assert PyQt6Recipe._version == "6.6.1"
assert PyQt6Recipe.depends == ['qt6', 'pyjnius', 'setuptools', 'pyqt6sip', 'hostpython3', 'pyqt_builder']
assert PyQt6Recipe.python_depends == []


class PyQt6RecipePinned(util.InheritedRecipeMixin, PyQt6Recipe):
    sha512sum = "c2ff8c47c9b0e43c009d0c90f565a54344e6f384c67dd30c2d422465d0702c07713acc0095c8b67827d1146675611c07d548ba282a26e41bb60a0a21977a7a64"


recipe = PyQt6RecipePinned()
