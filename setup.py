"""Build the compact native graph storage alongside the Python reference engine."""

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
        Extension(
            "axiom.engine",
            ["native/engine.cpp"],
            depends=["native/engine.hpp", "native/store.hpp", "native/free_index.hpp"],
            language="c++",
            extra_compile_args=["/std:c++17"]
            if sys.platform == "win32"
            else ["-std=c++17", "-g0"],
        ),
    ],
    package_data={"axiom": ["*.pyi", "py.typed"]},
)
