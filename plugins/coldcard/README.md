
# Coldcard Hardware Wallet Plugin

## Just the glue please

This code connects the public USB API and Electrum. Leverages all the good work that's been 
done my the Electrum team to support hardware wallets.

## TODO Items

- No effort yet to support translations, sorry.


### Ctags

- I find this command useful (at top level) ... but I'm a VIM user.

    ctags -f .tags electrum `find . -name ENV -prune -o -name \*.py`

### Working with latest ckcc-protocol

- at top level, do this:

    pip install -e git+ssh://git@github.com/Coldcard/ckcc-protocol.git#egg=ckcc-protocol

- but you'll need the https version of that, not ssh like I can.
- also a branch name would be good in there
- do `pip uninstall ckcc` first
- see <https://stackoverflow.com/questions/4830856>
