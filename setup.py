
# setup.py
import subprocess, shutil
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from wheel.bdist_wheel import bdist_wheel

class BinaryDistWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False  # platform-specific wheel

class build_py(_build_py):
    def run(self):
        # Build python modules into build_lib first
        super().run()

        root = Path(__file__).resolve().parent
        src_dir = root / "src"            # <-- your flat C src dir
        so_path = src_dir / "build" / "libmstp_agent.so"

        # Compile the shared library into src/build/
        print(f"[misty] make clean_build in {src_dir}")
        subprocess.check_call(["make", "clean_build"], cwd=str(src_dir))

        if not so_path.exists():
            raise RuntimeError(f"Expected {so_path} after build")

        # Copy the .so into the package in the build tree so it lands in the wheel
        pkg_out = Path(self.build_lib) / "misty" / "mstplib"
        pkg_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(so_path, pkg_out / "libmstp_agent.so")
        print(f"[misty] bundled libmstp_agent.so -> {pkg_out}")

def setup_packages():
    setup(
        name="misty",
        version="0.0.16",  # bump when publishing
        description="MSTP support for bacpypes",
        long_description="The misty package helps build bacpypes Applications that work on MS/TP Networks.",
        license="GNU General Public License v2.0",
        author="Riptide, Inc",
        author_email="raghavan@riptideio.com",
        url="https://github.com/riptideio/misty",
        packages=["misty", "misty.mstplib"],
        package_dir={"misty": "misty"},
        cmdclass={"bdist_wheel": BinaryDistWheel, "build_py": build_py},
        include_package_data=False,          # MANIFEST.in will NOT affect wheel contents
        # package_data not required because we copy the .so into build_lib above
        install_requires=["bacpypes>=0.18.0", "six>=1.15.0"],
        zip_safe=False,
    )

if __name__ == "__main__":
    setup_packages()

