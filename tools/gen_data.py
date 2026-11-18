"""
tools/gen_data.py — Sinh data/categories.csv (>= 200 mục, 6 nhóm) và data/test_domains.csv.

QUY TẮC AN TOÀN (đề §F2 + phụ lục): chỉ dùng tên miền công khai an toàn. Nhóm
"inappropriate" dùng TÊN MIỀN MÔ PHỎNG TRUNG TÍNH dưới *.test-block.example (miền .example
được IANA dành riêng cho tài liệu/thử nghiệm — RFC 2606, không bao giờ phân giải ra nội dung thật).

Chạy: python tools/gen_data.py
"""
import csv
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

EDUCATION = """
khanacademy.org wikipedia.org wiktionary.org wikimedia.org olm.vn hocmai.vn vuihoc.vn violympic.vn
hoc247.net vietjack.com loigiaihay.com hoc24.vn duolingo.com scratch.mit.edu mit.edu code.org coursera.org
edx.org britannica.com nationalgeographic.com natgeokids.com moet.gov.vn hcmus.edu.vn vnu.edu.vn
hust.edu.vn hcmut.edu.vn ueh.edu.vn hcm.edu.vn hanoi.edu.vn tratu.soha.vn cambridge.org
oxfordlearnersdictionaries.com merriam-webster.com dictionary.com mathsisfun.com ixl.com quizlet.com
brainpop.com starfall.com abcya.com funbrain.com nasa.gov smithsonianmag.com ted.com w3schools.com
geeksforgeeks.org stanford.edu harvard.edu ox.ac.uk cam.ac.uk geogebra.org desmos.com wolframalpha.com
kiddle.co ducksters.com pbslearningmedia.org readingiseasy.com storylineonline.net epic.com
typingclub.com tinkercad.com microbit.org arduino.cc python.org mozilla.org thuvienhoclieu.com
tienganh123.com elsaspeak.com monkey.edu.vn tuhoc365.vn vndoc.com toploigiai.vn sachhoc.com
"""
ENTERTAINMENT = """
youtube.com youtubekids.com netflix.com spotify.com disneyplus.com pbskids.org cartoonnetwork.com nickjr.com
nick.com zingmp3.vn nhaccuatui.com fptplay.vn vieon.vn galaxyplay.vn dailymotion.com vimeo.com soundcloud.com
imdb.com twitch.tv crunchyroll.com webtoons.com truyenqq.com mangatoon.mobi kidsa-z.com boomerang.com
lego.com disney.com dreamworks.com pixar.com sesamestreet.org bbc.co.uk cbeebies.com hbo.com
music.apple.com deezer.com tiki.vn shopee.vn lazada.vn
"""
SOCIAL = """
facebook.com fb.com messenger.com instagram.com tiktok.com twitter.com x.com snapchat.com reddit.com
discord.com discord.gg threads.net pinterest.com tumblr.com linkedin.com quora.com weibo.com vk.com
telegram.org t.me whatsapp.com line.me kakao.com wechat.com zalo.me chat.zalo.me bereal.com
mastodon.social bsky.app omegle.com
"""
GAMES = """
roblox.com rbxcdn.com minecraft.net epicgames.com fortnite.com steampowered.com steamcommunity.com ea.com
garena.vn garena.com leagueoflegends.com riotgames.com blizzard.com battle.net ubisoft.com playstation.com
xbox.com nintendo.com miniclip.com poki.com y8.com friv.com crazygames.com agar.io slither.io krunker.io
chess.com lichess.org zingplay.com vnggames.com vtcgame.vn genshin.hoyoverse.com hoyoverse.com
supercell.com clashofclans.com brawlstars.com pubg.com mobilelegends.com freefire.garena.vn
"""
UNCATEGORIZED = """
vnexpress.net tuoitre.vn thanhnien.vn dantri.com.vn vietnamnet.vn nhandan.vn baochinhphu.vn vtv.vn
bbc.com cnn.com reuters.com apnews.com google.com bing.com microsoft.com apple.com github.com
example.com example.org example.net weather.com accuweather.com
"""
INAPPROPRIATE = [f"adult-sim-{i:02d}.test-block.example" for i in range(1, 21)] + \
                [f"gambling-sim-{i:02d}.test-block.example" for i in range(1, 11)] + \
                [f"violence-sim-{i:02d}.test-block.example" for i in range(1, 6)]


def words(s: str) -> list[str]:
    return [w for w in s.split() if w]


def main():
    rows = []
    for cat, src in (("education", words(EDUCATION)), ("entertainment", words(ENTERTAINMENT)),
                     ("social", words(SOCIAL)), ("games", words(GAMES)), ("uncategorized", words(UNCATEGORIZED)),
                     ("inappropriate", INAPPROPRIATE)):
        rows += [(d, cat) for d in src]
    seen, uniq = set(), []
    for d, c in rows:
        if d not in seen:
            seen.add(d)
            uniq.append((d, c))
    DATA.mkdir(exist_ok=True)
    with open(DATA / "categories.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "category"])
        w.writerows(uniq)

    # Bộ kiểm thử theo phụ lục đề: 50 miền CẦN CHẶN + 20 miền giáo dục (đo dương tính giả)
    # + 10 giải trí thiếu nhi + 7 trò chơi (được phép, chỉ giới hạn giờ).
    test = []
    edu20 = words(EDUCATION)[:20]
    test += [(d, "education", "allow") for d in edu20]
    test += [(d, "entertainment", "allow") for d in ["pbskids.org", "youtubekids.com", "nickjr.com", "cartoonnetwork.com",
                                                    "sesamestreet.org", "cbeebies.com", "lego.com", "disney.com",
                                                    "zingmp3.vn", "webtoons.com"]]
    test += [(d, "games", "allow") for d in ["roblox.com", "minecraft.net", "poki.com", "chess.com", "y8.com",
                                            "friv.com", "crazygames.com"]]
    block = [(d, "social") for d in ["facebook.com", "instagram.com", "tiktok.com", "twitter.com", "snapchat.com",
                                     "reddit.com", "discord.com", "threads.net"]]
    block += [(d, "social-subdomain") for d in ["m.facebook.com", "www.instagram.com", "web.whatsapp.com",
                                                "vm.tiktok.com"]]
    block += [(d, "doh") for d in ["dns.google", "cloudflare-dns.com", "mozilla.cloudflare-dns.com",
                                   "doh.opendns.com", "dns.quad9.net"]]
    block += [("use-application-dns.net", "doh-canary")]
    sims = [f"adult-sim-{i:02d}.test-block.example" for i in range(1, 11)] + \
           [f"www.gambling-sim-{i:02d}.test-block.example" for i in range(1, 11)] + \
           [f"cdn.violence-sim-{i:02d}.test-block.example" for i in range(1, 6)] + \
           [f"img.adult-sim-{i:02d}.test-block.example" for i in range(11, 18)]
    block += [(d, "inappropriate-sim") for d in sims]
    assert len(block) == 50, len(block)
    test += [(d, g, "block") for d, g in block]
    with open(DATA / "test_domains.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "group", "expected"])
        w.writerows(test)
    print(f"categories.csv: {len(uniq)} mục; test_domains.csv: {len(test)} mục ({len(block)} cần chặn)")


if __name__ == "__main__":
    main()
