import hashlib
import os
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

from pdm.pep517.base import BuildError
from pdm.pep517.wheel import WheelBuilder


class EditableProject:
    """Copied from https://github.com/pfmoore/editables"""

    def __init__(self, project_name: str, project_dir: str) -> None:
        self.project_name = project_name
        self.project_dir = Path(project_dir)
        self.redirections: Dict[str, str] = {}
        self.path_entries: List[Path] = []

    def make_absolute(self, path: str) -> Path:
        return (self.project_dir / path).resolve()

    def map(self, name: str, target: str) -> None:
        if "." in name:
            raise BuildError(f"Cannot map {name} as it is not a top-level package")
        abs_target = self.make_absolute(target)
        if abs_target.is_dir():
            abs_target = abs_target / "__init__.py"
        if abs_target.is_file():
            self.redirections[name] = str(abs_target)
        else:
            raise BuildError(f"{target} is not a valid Python package or module")

    def add_to_path(self, dirname: str) -> None:
        self.path_entries.append(self.make_absolute(dirname))

    def files(self) -> Iterable[Tuple[str, str]]:
        yield f"{self.project_name}.pth", self.pth_file()
        if self.redirections:
            yield f"_{self.project_name}.py", self.bootstrap_file()

    def dependencies(self) -> Iterable[str]:
        if self.redirections:
            yield "editables"

    def pth_file(self) -> str:
        lines: List[str] = []
        if self.redirections:
            lines.append(f"import _{self.project_name}")
        for entry in self.path_entries:
            lines.append(str(entry))
        return "\n".join(lines)

    def bootstrap_file(self) -> str:
        bootstrap = [
            "from editables.redirector import RedirectingFinder as F",
            "F.install()",
        ]
        for name, path in self.redirections.items():
            bootstrap.append(f"F.map_module({name!r}, {path!r})")
        return "\n".join(bootstrap)


class EditableBuilder(WheelBuilder):
    def __init__(
        self, location: Union[str, Path], config_settings: Optional[Mapping[str, Any]]
    ) -> None:
        super().__init__(location, config_settings=config_settings)
        self.editables = EditableProject(
            self.meta.project_name, self.location.as_posix()
        )

    def _copy_module(self, wheel: zipfile.ZipFile) -> None:
        package_paths = self.meta.convert_package_paths()
        package_dir = self.meta.package_dir
        for package in package_paths.get("packages", []):
            if "." in package:
                continue
            self.editables.map(package, os.path.join(package_dir, package))

        for module in package_paths.get("py_modules", []):
            if "." in module:
                continue
            self.editables.map(module, os.path.join(package_dir, module + ".py"))

        super()._copy_module(wheel)

    def find_files_to_add(self, for_sdist: bool = False) -> List[Path]:
        return [
            p
            for p in super().find_files_to_add(for_sdist=for_sdist)
            if p.suffix != ".py"
        ]

    def _add_file_content(
        self, wheel: zipfile.ZipFile, rel_path: str, content: str
    ) -> None:
        print(f" - Adding {rel_path}")
        zinfo = zipfile.ZipInfo(rel_path)

        hashsum = hashlib.sha256()
        buf = content.encode("utf-8")
        hashsum.update(buf)

        wheel.writestr(zinfo, buf, compress_type=zipfile.ZIP_DEFLATED)
        size = len(buf)
        hash_digest = urlsafe_b64encode(hashsum.digest()).decode("ascii").rstrip("=")

        self._records.append((rel_path, hash_digest, str(size)))

    def _write_metadata(self, wheel: zipfile.ZipFile) -> None:
        for name, content in self.editables.files():
            self._add_file_content(wheel, name, content)
        self.meta._metadata.setdefault("dependencies", []).extend(
            self.editables.dependencies()
        )
        return super()._write_metadata(wheel)
