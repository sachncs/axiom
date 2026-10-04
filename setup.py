"""Build compact native graph storage for the paper matching modes."""

import sys

from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            "axiom.storage",
            ["native/storage.cpp"],
            depends=["native/store.hpp"],
            language="c++",
            extra_compile_args=["/std:c++17"]
            if sys.platform == "win32"
            else ["-std=c++17", "-g0"],
        ),
    ],
    package_data={"axiom": ["*.pyi", "py.typed"]},
)
