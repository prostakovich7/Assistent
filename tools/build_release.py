"""Сборка zip-архива демо-релиза для GitHub Releases.

    python tools/build_release.py v0.1   →   dist/Assistent-v0.1.zip

В архив идут только код, мок-данные, примеры, инструкции и bat-файлы.
Никаких .env, выгрузок CRM, журналов и отчётов — проверяется в конце.
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["README.md", "ЗАПУСК_ДЕМО.txt", "requirements.txt", "requirements-demo.txt",
         "Показать пример отчёта.bat", "Запустить агента.bat"]
DIRS = ["agent", "data/mock", "examples"]
FORBIDDEN = (".env", ".xlsx", ".csv", ".log", "state.json")


def main(version: str) -> Path:
    name = f"Assistent-{version}"
    out = ROOT / "dist" / f"{name}.zip"
    out.parent.mkdir(exist_ok=True)
    paths = [ROOT / f for f in FILES]
    for d in DIRS:
        paths += [p for p in sorted((ROOT / d).rglob("*"))
                  if p.is_file() and "__pycache__" not in p.parts]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            rel = p.relative_to(ROOT).as_posix()
            if p.name.endswith(FORBIDDEN) and p.name != ".env.example":
                raise SystemExit(f"В архив попал запрещённый файл: {rel}")
            data = p.read_bytes()
            if p.suffix == ".bat":  # cmd.exe надёжно работает только с переводами строк CRLF
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            z.writestr(f"{name}/{rel}", data)
    return out


if __name__ == "__main__":
    zip_path = main(sys.argv[1] if len(sys.argv) > 1 else "v0.1")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    print(f"{zip_path} — {zip_path.stat().st_size // 1024} КБ, файлов: {len(names)}")
    print("\n".join(names))
