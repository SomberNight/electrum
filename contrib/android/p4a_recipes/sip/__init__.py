from pythonforandroid.recipes.sip import SipRecipe


assert SipRecipe._version == "6.8.1"
assert SipRecipe.depends == ["setuptools", "packaging", "tomli", "python3"], SipRecipe.depends
assert SipRecipe.python_depends == []


class SipRecipePinned(SipRecipe):
    sha512sum = "315243ec94fa66165ea458b64ab11d5b682f17723148e4dbe844dc31d6d7b024458a58c68bf2643f0930a31f28821b85a99fa1b02431a9a2e1c0d8ddd1df3342"


recipe = SipRecipePinned()
