from pythonforandroid.recipes.pyqt_builder import PyQtBuilderRecipe


assert PyQtBuilderRecipe._version == "1.15.4"
assert PyQtBuilderRecipe.depends == ["sip", "packaging", "python3"]
assert PyQtBuilderRecipe.python_depends == []


class PyQtBuilderRecipePinned(PyQtBuilderRecipe):
    sha512sum = "ec0b9f7784a32af744111615b93f98d73f284bb752fd71359c798d3b093a01925823effea72c866a5f49f77e3dfc5dee4125bbb289f647d84000bf34b5db6931"


recipe = PyQtBuilderRecipePinned()
