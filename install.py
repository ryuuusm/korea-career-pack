#!/usr/bin/env python3
"""Copy korea-career-pack files into an existing career-ops checkout.

Usage:
    python install.py /path/to/career-ops --dry-run   # show what would happen
    python install.py /path/to/career-ops            # copy new files, skip existing ones
    python install.py /path/to/career-ops --force     # also overwrite files that differ

Safety rules:
- The target must look like career-ops (AGENTS.md and modes/ present).
- Existing files are never overwritten without --force; identical files are skipped.
- Every destination is resolved and must stay inside the target directory, and
  symlinked destinations are refused, so a crafted checkout cannot redirect writes.
- Nothing is deleted. To uninstall, remove the files listed in README.md.

Exit codes: 0 success, 1 some files were skipped because they differ, 2 usage/target error.
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

PACK_DIR = Path(__file__).resolve().parent / "pack"


def pack_files() -> List[Path]:
    """All files shipped in pack/, relative to pack/ (sorted for stable output)."""
    return sorted(p.relative_to(PACK_DIR) for p in PACK_DIR.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts)


def check_target(target: Path) -> Path:
    if not target.is_dir():
        raise SystemExit(f"error: target is not a directory: {target}")
    if not (target / "AGENTS.md").is_file() or not (target / "modes").is_dir():
        raise SystemExit(f"error: {target} does not look like a career-ops checkout "
                         "(AGENTS.md and modes/ expected)")
    return target.resolve()


def plan(target: Path, force: bool) -> List[Tuple[str, Path, Path]]:
    """Return (action, src, dst) for every pack file. action: copy|overwrite|same|skip."""
    actions = []
    for rel in pack_files():
        src = PACK_DIR / rel
        dst = target / rel
        # Refuse writes that would escape the target through '..' or symlinks.
        if dst.is_symlink() or any(p.is_symlink() for p in dst.parents if p != target and target in p.parents):
            raise SystemExit(f"error: refusing to write through a symlink: {dst}")
        resolved = dst.resolve()
        if target != resolved and target not in resolved.parents:
            raise SystemExit(f"error: destination escapes target: {dst}")
        if not dst.exists():
            actions.append(("copy", src, dst))
        elif filecmp.cmp(src, dst, shallow=False):
            actions.append(("same", src, dst))
        else:
            actions.append(("overwrite" if force else "skip", src, dst))
    return actions


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Install korea-career-pack into a career-ops checkout")
    ap.add_argument("target", help="path to your career-ops directory")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--force", action="store_true", help="overwrite files that differ")
    args = ap.parse_args(argv)

    try:
        target = check_target(Path(args.target).expanduser())
        actions = plan(target, args.force)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2

    labels = {"copy": "+ new      ", "overwrite": "! overwrite", "same": "= unchanged", "skip": "~ SKIPPED  "}
    for action, src, dst in actions:
        print(f"{labels[action]} {dst.relative_to(target)}")
        if args.dry_run or action in ("same", "skip"):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    skipped = [a for a in actions if a[0] == "skip"]
    if skipped:
        print(f"\n{len(skipped)} file(s) differ from the pack and were left untouched. "
              "Compare them, then re-run with --force to overwrite.", file=sys.stderr)
    if args.dry_run:
        print("\n(dry run: nothing was written)")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
