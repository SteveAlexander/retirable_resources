from setuptools import setup
import os
import sys

_here = os.path.abspath(os.path.dirname(__file__))

if sys.version_info[0] < 3:
    with open(os.path.join(_here, "README.md")) as f:
        long_description = f.read()
else:
    with open(os.path.join(_here, "README.md"), encoding="utf-8") as f:
        long_description = f.read()

version = {}
with open(os.path.join(_here, "retirable_resources", "version.py")) as f:
    exec(f.read(), version)

setup(
    name="retirable_resources",
    version=version["__version__"],
    description=("Retirable resources for Firestore."),
    long_description=long_description,
    author="Steve Alexander",
    author_email="steve@stevea.com",
    url="https://github.com/SteveAlexander/retirable_resources",
    download_url="https://github.com/SteveAlexander/retirable_resources/archive/refs/tags/0.1.7.tar.gz",
    license="MIT",
    packages=["retirable_resources"],
    install_requires=[
        "google-cloud-firestore>=2.1.3",
        "google-auth>=1.33.0",
    ],
    #   no scripts in this example
    #   scripts=['bin/a-script'],
    include_package_data=True,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
    ],
)
