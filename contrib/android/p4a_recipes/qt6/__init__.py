import os

from pythonforandroid.recipes.qt6 import Qt6Recipe

from pythonforandroid.util import load_source

util = load_source('util', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'util.py'))

assert Qt6Recipe._version == "6.5.3"
# assert Qt6Recipe._version == "6.5.3"
assert Qt6Recipe.depends == ['python3', 'hostqt6']
assert Qt6Recipe.python_depends == []

class Qt6RecipePinned(util.InheritedRecipeMixin, Qt6Recipe):
    sha512sum = "ca8ea3b81c121886636988275f7fa8ae6d19f7be02669e63ab19b4285b611057a41279db9532c25ae87baa3904b010e1db68b899cd0eda17a5a8d3d87098b4d5"


recipe = Qt6RecipePinned()
