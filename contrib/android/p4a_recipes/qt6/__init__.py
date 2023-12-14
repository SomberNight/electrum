import os

from pythonforandroid.recipes.qt6 import Qt6Recipe

from pythonforandroid.util import load_source

util = load_source('util', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'util.py'))

assert Qt6Recipe._version == "6.6.1"
# assert Qt6Recipe._version == "6.5.3"
assert Qt6Recipe.depends == ['python3', 'hostqt6']
assert Qt6Recipe.python_depends == []

class Qt6RecipePinned(util.InheritedRecipeMixin, Qt6Recipe):
    sha512sum = "76dfd01d06c228167dce8b523fd1cdf86787f183e61071fa1e165dfc786cc6ffdf2dc01ddbdd34af96a71a0e19a5e509b39abeecbca7d79f0f952176c9e21e34"


recipe = Qt6RecipePinned()
