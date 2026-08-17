"""Parse C header files to extract function signatures and struct definitions.

This is a deliberately lightweight parser intended for **automation** in the thesis
prototype. It uses regex-based extraction, which is not a full C AST parser, but is
sufficient for typical embedded middleware headers (typedef structs, simple function
prototypes).

Primary usage:
- Discover a block's init function prototype (e.g. `Filter3p3zInit`).
- Discover the parameter struct used by that init function (e.g. `FILTER_3P3Z_PARAMS_T`).

The output is used by `src.analysis.model_generator.generate_input_model()`.

CLI self-test:
    python src/analysis/header_parser.py <include_dir> [function_name] [struct_name]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FunctionParam:
    """Function parameter representation."""

    name: str
    c_type: str
    is_pointer: bool


@dataclass(frozen=True)
class FunctionSignature:
    """Function signature representation."""

    name: str
    return_type: str
    params: list[FunctionParam]


@dataclass(frozen=True)
class StructField:
    """Struct field representation."""

    name: str
    c_type: str
    comment: Optional[str] = None


@dataclass(frozen=True)
class StructDef:
    """Struct definition representation."""

    name: str
    fields: list[StructField]


class HeaderParser:
    """Parse C headers using regex.

    Notes:
    - This parser is intentionally simple.
    - It handles common patterns:
      * `typedef struct { ... } NAME;`
      * `struct NAME { ... };`
      * function prototypes like: `ret_t FuncName(type a, type *b);`
    """

    def __init__(self, include_dir: Path | None = None, *, target_repo: Path | None = None):
        """Initialize parser with include directory.

        Args:
            include_dir: Directory containing `*.h` files.
            target_repo: Optional repo root to auto-detect include directory for common
                layouts (e.g. mtb-mw-pctrl stores headers under blocks/).

        Raises:
            FileNotFoundError: if include_dir does not exist and auto-detection fails.
        """

        if include_dir is None:
            if target_repo is None:
                raise FileNotFoundError(
                    "Include directory not provided and target_repo not set for auto-detect"
                )
            include_dir = self.auto_detect_include_dir(Path(target_repo))

        self.include_dir = Path(include_dir)
        if not self.include_dir.exists():
            raise FileNotFoundError(f"Include directory not found: {self.include_dir}")

    @staticmethod
    def auto_detect_include_dir(target_repo: Path) -> Path:
        """Best-effort include dir discovery.

        For mtb-mw-pctrl, headers live under `<repo>/blocks/`.
        """

        candidate_dirs = [
            target_repo / "include",
            target_repo / "inc",
            target_repo / "blocks",
            target_repo,
        ]

        for d in candidate_dirs:
            if d.exists() and any(d.rglob("*.h")):
                return d

        raise FileNotFoundError(
            "Include directory not found. Tried: "
            + ", ".join(str(d) for d in candidate_dirs)
        )


    def find_function(self, func_name: str) -> Optional[FunctionSignature]:
        """Find a function prototype in header files.

        Args:
            func_name: Function name to search for.

        Returns:
            FunctionSignature if found, else None.
        """

        for header in self.include_dir.glob("**/*.h"):
            try:
                content = header.read_text(errors="ignore")
            except Exception:
                continue

            # return_type func_name(params...);
            pattern = rf"(\w+(?:\s+\w+)*)\s+{re.escape(func_name)}\s*\((.*?)\)\s*;"
            match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
            if match:
                return_type = match.group(1).strip()
                params_str = match.group(2).strip()
                params = self._parse_params(params_str)
                return FunctionSignature(func_name, return_type, params)

        return None

    def find_struct(self, struct_name: str) -> Optional[StructDef]:
        """Find a struct definition in headers.

        Args:
            struct_name: Struct name to search for.

        Returns:
            StructDef if found, else None.
        """

        for header in self.include_dir.glob("**/*.h"):
            try:
                content = header.read_text(errors="ignore")
            except Exception:
                continue

            # Try typedef struct { ... } NAME;
            pattern = rf"typedef\s+struct\s*\{{(.*?)\}}\s*{re.escape(struct_name)}\s*;"
            match = re.search(pattern, content, re.DOTALL)

            if not match:
                # Try struct NAME { ... };
                pattern2 = rf"struct\s+{re.escape(struct_name)}\s*\{{(.*?)\}}\s*;"
                match = re.search(pattern2, content, re.DOTALL)

            if match:
                body = match.group(1)
                fields = self._parse_struct_fields(body)
                return StructDef(struct_name, fields)

        return None

    def _parse_params(self, params_str: str) -> list[FunctionParam]:
        """Parse function parameter list."""

        params: list[FunctionParam] = []
        if not params_str or params_str.strip() == "void":
            return params

        parts = self._smart_split(params_str, ",")
        for param in parts:
            param = param.strip()
            if not param:
                continue

            is_pointer = "*" in param
            param_clean = param.replace("*", " ").strip()
            toks = param_clean.split()

            if len(toks) >= 2:
                name = toks[-1]
                c_type = " ".join(toks[:-1])
                params.append(FunctionParam(name=name, c_type=c_type, is_pointer=is_pointer))
            elif len(toks) == 1:
                params.append(FunctionParam(name="", c_type=toks[0], is_pointer=is_pointer))

        return params

    def _parse_struct_fields(self, body: str) -> list[StructField]:
        """Parse struct body to extract fields."""

        fields: list[StructField] = []

        for raw in body.split(";"):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("//"):
                continue

            comment: Optional[str] = None
            if "//" in line:
                line, comment = line.split("//", 1)
                line = line.strip()
                comment = comment.strip() if comment else None

            if not line:
                continue

            # Remove simple array brackets, keep name.
            line = re.sub(r"\[(\d+)\]", "", line).strip()

            toks = line.split()
            if len(toks) < 2:
                continue

            name = toks[-1].replace("*", "").strip()
            c_type = " ".join(toks[:-1]).replace("*", "").strip()

            fields.append(StructField(name=name, c_type=c_type, comment=comment))

        return fields

    def _smart_split(self, text: str, delimiter: str) -> list[str]:
        """Split by delimiter, but not inside parentheses."""

        parts: list[str] = []
        current: list[str] = []
        depth = 0

        for ch in text:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == delimiter and depth == 0:
                parts.append("".join(current))
                current = []
                continue
            current.append(ch)

        if current:
            parts.append("".join(current))

        return parts


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print(
            "Usage: python header_parser.py <include_dir> [function_name] [struct_name]\n"
            "   or: python header_parser.py --target <repo_root> [function_name] [struct_name]"
        )
        raise SystemExit(1)

    if sys.argv[1] == "--target":
        if len(sys.argv) < 3:
            print("Missing repo_root after --target")
            raise SystemExit(1)
        parser = HeaderParser(None, target_repo=Path(sys.argv[2]))
        arg_offset = 1
    else:
        parser = HeaderParser(Path(sys.argv[1]))
        arg_offset = 0


    if len(sys.argv) >= 3 + arg_offset:
        func = parser.find_function(sys.argv[2 + arg_offset])

        if func:
            print(f"\n✅ Found function: {func.name}")
            print(f"   Return type: {func.return_type}")
            print("   Parameters:")
            for p in func.params:
                ptr = "*" if p.is_pointer else ""
                print(f"     - {p.c_type}{ptr} {p.name}")
        else:
            print(f"\n❌ Function '{sys.argv[2 + arg_offset]}' not found")


    if len(sys.argv) >= 4 + arg_offset:
        struct = parser.find_struct(sys.argv[3 + arg_offset])

        if struct:
            print(f"\n✅ Found struct: {struct.name}")
            print("   Fields:")
            for f in struct.fields:
                c = f" // {f.comment}" if f.comment else ""
                print(f"     - {f.c_type} {f.name}{c}")
        else:
            print(f"\n❌ Struct '{sys.argv[3 + arg_offset]}' not found")

