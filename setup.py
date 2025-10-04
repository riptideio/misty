# setup.py
import sys, subprocess, shutil
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from wheel.bdist_wheel import bdist_wheel

class BinaryDistWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False  # wheel is platform-specific

class build_py(_build_py):
    def run(self):
        super().run()

        project_root = Path(__file__).resolve().parent
        mstplib_dir = project_root / "misty" / "mstplib"
        if not (mstplib_dir / "Makefile").exists():
            raise RuntimeError(f"Makefile not found in {mstplib_dir}")

        # 1) Compile using your Makefile target
        print(f"[misty] make clean_build in {mstplib_dir}")
        subprocess.check_call(["make", "clean_build"], cwd=str(mstplib_dir))

        # 2) We build a single canonical filename on all platforms
        found = mstplib_dir / "libmstp_agent.so"
        if not found.exists():
            raise RuntimeError("Expected misty/mstplib/libmstp_agent.so after build")


        # 3) Copy into the built package so it lands in the wheel
        pkg_out = Path(self.build_lib) / "misty" / "mstplib"
        pkg_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, pkg_out / found.name)
        print(f"[misty] bundled {found.name} -> {pkg_out}")


def setup_packages():
    setup(
        name="misty",
        version="0.0.15",  # bump
        description="MSTP support for bacpypes",
        long_description=(
            "The misty package helps build bacpypes Applications that work on MS/TP Networks. "
            "BIP (BACnet/IP) applications can be easily ported to use misty."
        ),
        license="GNU General Public License v2.0",
        author="Riptide, Inc",
        author_email="raghavan@riptideio.com",
        url="https://github.com/riptideio/misty",
        packages=["misty", "misty.mstplib"],
        package_dir={"misty": "misty"},
        cmdclass={"bdist_wheel": BinaryDistWheel, "build_py": build_py},
        install_requires=["bacpypes>=0.18.0", "six>=1.15.0"],
        scripts=[],

        include_package_data=False,  # MANIFEST.in will NOT affect the wheel
        package_data={"misty": ["mstplib/libmstp_agent.so"]},
        zip_safe=False
    )

if __name__ == "__main__":
    setup_packages()

