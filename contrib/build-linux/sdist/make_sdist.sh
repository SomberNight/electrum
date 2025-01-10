#!/bin/bash

set -e

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../../.."
CONTRIB="$PROJECT_ROOT/contrib"
CONTRIB_SDIST="$CONTRIB/build-linux/sdist"
CONTRIB_APPIMAGE="$CONTRIB/build-linux/appimage"
# ^ FIXME rm
DISTDIR="$PROJECT_ROOT/dist"
LOCALE="$PROJECT_ROOT/electrum/locale"
BUILDDIR="$CONTRIB_SDIST/build"
CACHEDIR="$CONTRIB_SDIST/.cache"

. "$CONTRIB"/build_tools_util.sh

git -C "$PROJECT_ROOT" rev-parse 2>/dev/null || fail "Building outside a git clone is not supported."



PYTHON_VERSION=3.11.9
PY_VER_MAJOR="3.11"  # as it appears in fs paths

rm -rf "$BUILDDIR"
mkdir -p "$BUILDDIR" "$CACHEDIR"

download_if_not_exist "$CACHEDIR/Python-$PYTHON_VERSION.tar.xz" "https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tar.xz"
verify_hash "$CACHEDIR/Python-$PYTHON_VERSION.tar.xz" "9b1e896523fc510691126c864406d9360a3d1e986acbda59cda57b5abda45b87"

info "building python."
tar xf "$CACHEDIR/Python-$PYTHON_VERSION.tar.xz" -C "$CACHEDIR"
(
    if [ -f "$CACHEDIR/Python-$PYTHON_VERSION/python" ]; then
        info "python already built, skipping"
        exit 0
    fi
    cd "$CACHEDIR/Python-$PYTHON_VERSION"
    LC_ALL=C export BUILD_DATE=$(date -u -d "@$SOURCE_DATE_EPOCH" "+%b %d %Y")
    LC_ALL=C export BUILD_TIME=$(date -u -d "@$SOURCE_DATE_EPOCH" "+%H:%M:%S")
    # Patches taken from Ubuntu http://archive.ubuntu.com/ubuntu/pool/main/p/python3.11/python3.11_3.11.6-3.debian.tar.xz
    patch -p1 < "$CONTRIB_APPIMAGE/patches/python-3.11-reproducible-buildinfo.diff"
    ./configure \
        --cache-file="$CACHEDIR/python.config.cache" \
        --prefix="$BUILDDIR/usr" \
        --enable-ipv6 \
        --enable-shared \
        -q
    make "-j$CPU_COUNT" -s || fail "Could not build Python"
)
info "installing python."
(
    cd "$CACHEDIR/Python-$PYTHON_VERSION"
    make -s install > /dev/null || fail "Could not install Python"
)


function built_python() {
    env \
        PYTHONNOUSERSITE=1 \
        LD_LIBRARY_PATH="$BUILDDIR/usr/lib:$BUILDDIR/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}" \
        "$BUILDDIR/usr/bin/python${PY_VER_MAJOR}" "$@"
}

python='built_python'







"$python" --version || fail "python interpreter not found"

break_legacy_easy_install

"$python" -m pip install --upgrade --break-system-packages pip build

"$python" -m pip install --break-system-packages --no-build-isolation --no-dependencies --no-warn-script-location \
    --cache-dir "$PIP_CACHE_DIR" -r "$CONTRIB/deterministic-build/requirements-build-base.txt"

rm -rf "$PROJECT_ROOT/packages/"
if ([ "$OMIT_UNCLEAN_FILES" != 1 ]); then
    "$CONTRIB"/make_packages.sh || fail "make_packages failed"
fi

git submodule update --init

(
    # By default, include both source (.po) and compiled (.mo) locale files in the source dist.
    # Set option OMIT_UNCLEAN_FILES=1 to exclude the compiled locale files
    # see https://askubuntu.com/a/144139 (also see MANIFEST.in)
    rm -rf "$LOCALE"
    cp -r "$CONTRIB/deterministic-build/electrum-locale/locale/" "$LOCALE/"
    if ([ "$OMIT_UNCLEAN_FILES" != 1 ]); then
        "$CONTRIB/build_locale.sh" "$LOCALE" "$LOCALE"
    fi
)

if ([ "$OMIT_UNCLEAN_FILES" = 1 ]); then
    # FIXME side-effecting repo... though in practice, this script probably runs in fresh_clone
    rm -f "$PROJECT_ROOT/electrum/paymentrequest_pb2.py"
fi

(
    set -x
    cd "$PROJECT_ROOT"

    find -exec touch -h -d '2000-11-11T11:11:11+00:00' {} +

    # note: .zip sdists would not be reproducible due to https://bugs.python.org/issue40963
    if ([ "$OMIT_UNCLEAN_FILES" = 1 ]); then
        PY_DISTDIR="dist/_sourceonly" # The DISTDIR variable of this script is only used to find where the output is *finally* placed.
    else
        PY_DISTDIR="dist"
    fi

    "$python" --version || fail "python interpreter not found 1"
    TZ=UTC \
        PYTHONNOUSERSITE=1 \
        LD_LIBRARY_PATH="$BUILDDIR/usr/lib:$BUILDDIR/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}" \
        faketime -f '2000-11-11 11:11:11' \
        "$BUILDDIR/usr/bin/python${PY_VER_MAJOR}" --version || fail "python interpreter not found 2"

    #TZ=UTC faketime -f '2000-11-11 11:11:11' "$python" setup.py --quiet sdist --format=gztar --dist-dir="$PY_DISTDIR"
    TZ=UTC \
        PYTHONNOUSERSITE=1 \
        LD_LIBRARY_PATH="$BUILDDIR/usr/lib:$BUILDDIR/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}" \
        faketime -f '2000-11-11 11:11:11' \
        "$BUILDDIR/usr/bin/python${PY_VER_MAJOR}" -m build --sdist . --no-isolation --outdir="$PY_DISTDIR"
    if ([ "$OMIT_UNCLEAN_FILES" = 1 ]); then
        "$python" <<EOF
import importlib.util
import os

# load version.py; needlessly complicated alternative to "imp.load_source":
version_spec = importlib.util.spec_from_file_location('version', 'electrum/version.py')
version_module = importlib.util.module_from_spec(version_spec)
version_spec.loader.exec_module(version_module)

VER = version_module.ELECTRUM_VERSION
os.rename(f"dist/_sourceonly/Electrum-{VER}.tar.gz", f"dist/Electrum-sourceonly-{VER}.tar.gz")
EOF
        rmdir "$PY_DISTDIR"
    fi
)


info "done."
ls -la "$DISTDIR"
sha256sum "$DISTDIR"/*
