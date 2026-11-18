"""tools/hash_exe.py — In SHA-256 của tệp .exe để dán vào dashboard (Web & ứng dụng -> theo mã băm).

    python tools/hash_exe.py C:\\Windows\\System32\\notepad.exe
Thử nghiệm đề F2: copy notepad.exe thành game.exe -> hai tệp cùng băm -> agent vẫn nhận diện.
"""
import hashlib
import sys

for path in sys.argv[1:]:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    print(f"{h.hexdigest()}  {path}")
