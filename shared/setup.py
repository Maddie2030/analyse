from setuptools import setup, find_packages

setup(
    name="manhwa-shared",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "sqlalchemy==2.0.36",
        "asyncpg==0.30.0",
        "redis==5.2.1",
        "argon2-cffi==23.1.0",
        "httpx==0.28.1",
        "pydantic==2.10.4",
        "pydantic-settings==2.7.0",
    ],
)
