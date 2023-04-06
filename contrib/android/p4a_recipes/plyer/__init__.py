from pythonforandroid.recipe import PythonRecipe


assert PythonRecipe.depends == ['python3']
assert PythonRecipe.python_depends == []


class PlyerRecipePinned(PythonRecipe):
    version = "1a5d4177862569aa23ecc38d782a4533db8e9431"
    url = "git+https://github.com/SomberNight/plyer"
    depends = ["setuptools"]


recipe = PlyerRecipePinned()
