from setuptools import setup, find_packages

package_name = "warehouse_event_system"

setup(
  name=package_name,
  version="0.1.0",
  packages=find_packages(exclude=["test"]),
  data_files=[
    ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
    (f"share/{package_name}", ["package.xml"]),
    (f"lib/{package_name}", []),
  ],
  install_requires=[
    "setuptools",
    "asyncpg",
  ],
  zip_safe=True,
  maintainer="Songhwa Chae",
  maintainer_email="songhwachae93@gmail.com",
  description="Event system: semantic state transitions → orchestration triggers",
  license="MIT",
  entry_points={
    "console_scripts": [],
  },
)
