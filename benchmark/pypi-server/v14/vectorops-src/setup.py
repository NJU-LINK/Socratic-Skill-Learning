from setuptools import find_packages, setup


setup(
    name="vectorops",
    version="0.1.0",
    description="Vector operations package for a local package index task.",
    author="Task Author",
    author_email="noreply@example.com",
    packages=find_packages(include=["vectorops", "vectorops.*"]),
)
