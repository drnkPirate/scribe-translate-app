import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "build_sidecar", Path(__file__).parents[1] / "scripts" / "build_sidecar.py",
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildSidecarTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "macOS framework symlinks require a POSIX host")
    def test_packaging_preserves_python_framework_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work, output = root / "build", root / "dist"
            web = root / "sidecar" / "web"
            web.mkdir(parents=True)
            (web / "en.json").write_text("{}")
            models = root / "transformers"
            for name in ("auto", "encoder_decoder", "marian"):
                (models / name).mkdir(parents=True)
            specs = {
                "silero_vad": SimpleNamespace(submodule_search_locations=[str(root)]),
                "transformers.models": SimpleNamespace(submodule_search_locations=[str(models)]),
            }

            def freeze(*args, **kwargs):
                framework = work / "dist" / "scribe-translate-server" / "_internal" / "Python.framework"
                version = framework / "Versions" / "3.12"
                (version / "Resources").mkdir(parents=True)
                (version / "Python").write_bytes(b"python-runtime")
                (version / "Resources" / "Info.plist").write_text("framework metadata")
                (framework / "Versions" / "Current").symlink_to("3.12")
                (framework / "Python").symlink_to("Versions/Current/Python")
                (framework / "Resources").symlink_to("Versions/Current/Resources")

            with (
                patch.multiple(builder, ROOT=root, WORK=work, OUTPUT=output),
                patch.object(builder.importlib.util, "find_spec", side_effect=specs.get),
                patch.object(builder.subprocess, "run", side_effect=freeze),
            ):
                builder.main()
            framework = output / "_internal" / "Python.framework"
            for relative in ("Python", "Resources", "Versions/Current"):
                self.assertTrue((framework / relative).is_symlink(), relative)
            self.assertEqual((framework / "Python").read_bytes(), b"python-runtime")


if __name__ == "__main__":
    unittest.main()
