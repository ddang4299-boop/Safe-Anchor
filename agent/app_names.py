"""
agent/app_names.py — Tên hiển thị thân thiện cho tên tệp .exe, DÙNG CHUNG cho dashboard (server/reports.py)
và OGK Kids (Tray): phụ huynh và trẻ đọc "Microsoft Word" dễ hơn "winword.exe".
Chỉ là nhãn hiển thị: dữ liệu gốc và luật chặn vẫn dùng tên tệp/SHA-256.
"""
from __future__ import annotations

APP_NAMES = {
    "winword.exe": "Microsoft Word", "excel.exe": "Microsoft Excel", "powerpnt.exe": "Microsoft PowerPoint",
    "onenote.exe": "OneNote", "msedge.exe": "Microsoft Edge", "chrome.exe": "Chrome", "firefox.exe": "Firefox",
    "opera.exe": "Opera", "brave.exe": "Brave", "minecraft.exe": "Minecraft",
    "minecraftlauncher.exe": "Minecraft Launcher", "minecraft.windows.exe": "Minecraft Education",
    "robloxplayerbeta.exe": "Roblox", "steam.exe": "Steam", "epicgameslauncher.exe": "Epic Games",
    "leagueclient.exe": "Liên Minh Huyền Thoại", "riotclientservices.exe": "Riot Client",
    "geogebra.exe": "GeoGebra", "scratch 3.exe": "Scratch 3", "mspaint.exe": "Paint", "notepad.exe": "Notepad",
    "spotify.exe": "Spotify", "vlc.exe": "VLC", "discord.exe": "Discord", "zalo.exe": "Zalo",
    "telegram.exe": "Telegram", "code.exe": "Visual Studio Code", "calc.exe": "Máy tính (Calculator)",
    "explorer.exe": "File Explorer", "nslookup.exe": "nslookup",
}


def app_display(exe: str | None) -> str:
    """'winword.exe' -> 'Microsoft Word'; tên lạ thì bỏ đuôi .exe và viết hoa chữ đầu."""
    key = (exe or "").strip().lower()
    if key in APP_NAMES:
        return APP_NAMES[key]
    base = key[:-4] if key.endswith(".exe") else key
    return (base[:1].upper() + base[1:]) if base else (exe or "")
