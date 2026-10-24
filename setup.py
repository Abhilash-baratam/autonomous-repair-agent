from setuptools import setup, find_namespace_packages

setup(
    name="autonomous-repair-agent",
    version="1.0.0",
    description="Autonomous AI Agent that isolates, debugs, verifies, and patches code bugs.",
    author="Autonomous Agent Team",
    packages=find_namespace_packages(
        include=["agent", "agent.*", "execution_runtime", "execution_runtime.*"]
    ),
    py_modules=["Cli"],
    install_requires=[
        "langchain>=0.2.0",
        "langchain-core>=0.2.0",
        "langchain-google-genai>=1.0.0",
        "pytest>=8.0.0",
        "python-dotenv>=1.0.0",
        "pydantic>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "repair-agent=Cli:main",
        ],
    },
    python_requires=">=3.10",
)