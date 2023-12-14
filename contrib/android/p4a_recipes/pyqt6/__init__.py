import os

from pythonforandroid.recipes.pyqt6 import PyQt6Recipe
from pythonforandroid.util import load_source

util = load_source('util', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'util.py'))


assert PyQt6Recipe._version == "6.6.0"
assert PyQt6Recipe.depends == ['qt6', 'pyjnius', 'setuptools', 'pyqt6sip', 'hostpython3', 'pyqt_builder']
assert PyQt6Recipe.python_depends == []


class PyQt6RecipePinned(util.InheritedRecipeMixin, PyQt6Recipe):
    sha512sum = "2fe8640b1dc82aa1da6064da2ef6c4ee81216ed34f28211b69d22c5ea00f782298f5a6a94d32ab00c3ee095abf15d2182a17324cd132458580f5659e789686e3"


recipe = PyQt6RecipePinned()
