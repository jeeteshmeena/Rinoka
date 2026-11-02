# Rinoka 🛡

**Rinoka** is an AI-powered Telegram group guardian. It removes porn, sexual content, scams, phishing and malware on its own, makes new members accept your rules before they can chat, and does all the usual group management work.

Rinoka is a fork of [Anjani](https://github.com/userbotindo/Anjani) by the UserbotIndo team, released under the same GPL-3.0 license.

## What's new in Rinoka

### 🛡 AI Shield (no filters to set up)
Rinoka reads every message and decides by itself:
- **Text and captions**: English, Hindi and Hinglish, including tricks like 𝓯𝓪𝓷𝓬𝔂 fonts, `p.o.r.n`, l33t speak and hidden characters.
- **Photos, stickers, GIF and video thumbnails**: a local nudity detection model (NudeNet) runs on your own server, free and unlimited.
- **Links**: shorteners are expanded, then checked for adult sites, fake Telegram/bank look-alikes, APK/EXE downloads, punycode and risky domains, plus Google Safe Browsing.
- **Names and bios** of people who join ("Hot girl DM for video call" accounts get banned on arrival).
- **Google Gemini (free tier)** judges anything borderline and catches new scam styles.
- Flagged stickers and media are remembered, so repeat spam is removed instantly, and a whole sticker pack is blocked after repeated hits.

Commands: `/aishield on|off`, `/aiaction ban|mute|warn|delete`, `/aisens low|medium|high`, `/aiallow <domain>`, `/aiscan` (reply).

### 📜 T&C Gate
New members must accept the group's Terms & Conditions first.
- **Join requests** (turn on *Approve new members*): the requester gets the rules in DM with **I Agree / Decline** buttons and is approved only after agreeing.
- **Direct joins**: the member is muted until they press **I Agree**, and removed if they ignore it.

Commands: `/tnc on|off`, `/settnc <rules>`, `/resettnc`, `/tnctimeout <minutes>`.

### ✨ New Telegram UI
Rinoka uses the latest Bot API features through `rinoka/util/botapi.py`: coloured buttons (green/red/blue), Rich Messages with headings, lists and expandable quotes, and ephemeral messages. Everything falls back to normal messages if Telegram rejects a feature.

## Requirements
- Python 3.10 (Docker image included)
- Telegram `API_ID` and `API_HASH` from https://my.telegram.org/apps
- Bot token from [@BotFather](https://t.me/BotFather)
- MongoDB (free MongoDB Atlas M0 works)
- Optional, free: `GEMINI_API_KEY` from https://aistudio.google.com/apikey and `SAFE_BROWSING_KEY` from Google Cloud

## Deploy on an Oracle Cloud VPS (Ubuntu)

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker

git clone https://github.com/jeeteshmeena/Rinoka.git
cd Rinoka
cp config.env_sample config.env
nano config.env          # fill API_ID, API_HASH, BOT_TOKEN, OWNER_ID, DB_URI, GEMINI_API_KEY

docker compose up -d --build
docker compose logs -f   # watch it start
```

Then add the bot to your group as admin with **Delete messages**, **Ban users** and **Invite users** rights, and run `/tnc on` there.

Update later with `git pull && docker compose up -d --build`.

## Plugins
Custom plugins go in `rinoka/custom_plugins/`. See `example.py` there and Anjani's [plugin guide](https://userbotindo.com/anjani/docs/plugin/creating-your-own-plugin).

## Credits
- [Anjani](https://github.com/userbotindo/Anjani) and [all its contributors](https://github.com/userbotindo/Anjani/graphs/contributors)
- [Marie](https://github.com/PaulSonOfLars/tgbot), [Pyrobud](https://github.com/kdrag0n/pyrobud)
- [NudeNet](https://github.com/notAI-tech/NudeNet)
