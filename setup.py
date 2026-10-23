"""Optional native sampling; installations without a C compiler keep NumPy."""

import os

from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            "fromthecraft._mesh_native",
            ["src/fromthecraft/_mesh_native.c"],
            extra_compile_args=["/fp:strict"] if os.name == "nt" else ["-fno-fast-math", "-ffp-contract=off"],
            optional=True,
        )
    ]
)
