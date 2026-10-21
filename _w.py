import sys, base64, pathlib
p = pathlib.Path(sys.argv[1])
raw = base64.b64decode(sys.argv[2])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(raw)
print("wrote", p.as_posix(), len(raw))