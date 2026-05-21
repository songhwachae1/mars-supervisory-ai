from setuptools import setup, find_packages

package_name = "warehouse_aggregator"

setup(
  name=package_name,
  version="0.1.0",
  packages=find_packages(exclude=["test"]),
  data_files=[
    ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
    (f"share/{package_name}", ["package.xml"]),
  ],
  install_requires=[
    "setuptools",
    "asyncpg",
  ],
  zip_safe=True,
  maintainer="you",
  maintainer_email="you@example.com",
  description="Context Aggregator: ROS2 → PostgreSQL Blackboard",
  license="MIT",
  entry_points={
    "console_scripts": [
      "aggregator_node = aggregator.aggregator_node:main",
    ],
  },
)
