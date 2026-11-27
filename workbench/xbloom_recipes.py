"""File-backed xBloom recipe library. Validation and persistence only; no BLE.

The filename is the recipe's name/version. Machine JSON stays unchanged, with
no parallel metadata database. Publishing is atomic and cannot replace a file.
"""
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from xbloom_bridge.protocol import MAX_RECIPE_BYTES, ProtocolError, parse_recipe
from xbloom_bridge.recording import recipe_digest


SUFFIX = ".recipe.json"
NAME_RE = re.compile(r"[A-Za-z0-9\u3400-\u9fff][A-Za-z0-9\u3400-\u9fff_-]{0,79}\Z")


def validate_name(name):
    if type(name) is not str or not NAME_RE.fullmatch(name) or name == "validate":
        raise ValueError("配方名称须为1–80个中文、英文字母或数字，可含连字符和下划线；validate为保留名")
    return name


def preview_recipe(raw):
    recipe = parse_recipe(raw)
    return {"recipe": recipe, "sha256": recipe_digest(recipe),
            "ratio": recipe["recipe"]["grandWater"] / recipe["doseGrams"]}


def _item(name, recipe):
    return {"name": name, "filename": name + SUFFIX,
            "recipe": recipe, "sha256": recipe_digest(recipe)}


class RecipeStore:
    def __init__(self, root):
        self.root = Path(root)

    def _read(self, name):
        name = validate_name(name)
        path = self.root / (name + SUFFIX)

        def opener(filename, flags):
            return os.open(filename, flags | os.O_NOFOLLOW | os.O_NONBLOCK)

        # Refuse symlinks and non-files instead of reading outside the library
        # or waiting on a FIFO. The check applies to the opened inode.
        with open(path, "rb", opener=opener) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ProtocolError("配方必须是普通文件")
            raw = stream.read(MAX_RECIPE_BYTES + 1)
        return raw, parse_recipe(raw)

    def get(self, name):
        _, recipe = self._read(name)
        return _item(name, recipe)

    def download(self, name):
        raw, _ = self._read(name)
        return raw

    def list(self):
        items, errors = [], []
        if not self.root.exists():
            return {"items": items, "errors": errors}
        for path in sorted(self.root.glob("*" + SUFFIX)):
            try:
                items.append(self.get(path.name[:-len(SUFFIX)]))
            except (OSError, ValueError) as exc:
                errors.append({"filename": path.name, "error": str(exc)})
        return {"items": items, "errors": errors}

    def create(self, name, raw):
        name = validate_name(name)
        recipe = parse_recipe(raw)  # Before creating directories or temp files.
        body = (json.dumps(recipe, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        # Also verify the bytes actually persisted. No separate, weaker schema.
        parse_recipe(body)
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / (name + SUFFIX)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".recipe-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            # link is an atomic, no-replace publish on this local filesystem.
            # Competing saves of the same name: one wins; others get EEXIST.
            os.link(temporary, target)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return _item(name, recipe)
