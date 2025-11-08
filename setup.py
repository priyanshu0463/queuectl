"""Setup script for QueueCTL."""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="queuectl",
    version="1.0.0",
    author="QueueCTL Team",
    description="A CLI-based background job queue system",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "typer>=0.20.0",
        "rich>=14.2.0",
    ],
    entry_points={
        "console_scripts": [
            "queuectl=queuectl.cli:app",
        ],
    },
)

