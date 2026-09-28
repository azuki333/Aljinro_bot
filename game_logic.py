import discord
import urllib.request
import urllib.error
import json
import asyncio
import os
import random

# --- 環境変数の取得 ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0"
}

# --- AIキャラクター設定（5人） ---
AI_CHARACTERS = [
    {"name": "レン", "desc": "20代男性。冷静沈着で論理的。矛盾や怪しい発言を見逃さず詰めるタイプ。"},
    {"name": "ユイ", "desc": "17歳女子高生。直感重視で天然だが直感が当たる。"},
    {"name": "Gemini-A", "desc": "確率とログ分析重視の分析派。"},
    {"name": "Gemini-B", "desc": "心理戦が得意なブラフ担当。"},
    {"name": "タクミ", "desc": "30代ベテラン。盤面を乱して様子を見る戦略派。"}
]

ROLE_EMOJIS = {
    "人狼": "🐺",
    "市民": "👤",
    "占い師": "🔮",
    "怪盗": "🕵️",
    "狩人": "🎯",
    "てるてる": "☀️",
    "魔女っ子": "🧙‍♀️",
    "狂人": "🤫"
}

# --- ゲーム状態管理 ---
game = {
    "is_running": False,
    "mode": None,
    "phase": "idle",
    "channel": None,
    "players": {},
    "center_cards": [],
    "votes": {},
    "hunter_targets": {},
    "turn_count": 0,
    "discussion_task": None,
    "history": [],
    "selected_roles": {
        "人狼": 2,
        "市民": 3,
        "占い師": 1,
        "怪盗": 1,
        "狩人": 0,
        "てるてる": 0,
        "魔女っ子": 0,
        "狂人": 0
    }
}

async def send_split_message(channel, content):
    if not content or not channel:
        return
    for i in range(0, len(content), 1900):
        try:
            await channel.send(content[i:i+1900])
        except Exception as e:
            print(f"[送信エラー]: {e}")

def _sync_call_llm(prompt_content, debug=False):
    errors = []
    if GEMINI_API_KEY:
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt_content}]}]}
            req = urllib.request.Request(gemini_url, data=json.dumps(payload).encode('utf-8'), headers=HTTP_HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "candidates" in data and len(data["candidates"]) > 0:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    if len(text) > 5:
                        return (text if not debug else f"【Gemini成功】\n{text}")
        except Exception as e:
            errors.append(f"Gemini Error: {e}")

    if OPENAI_API_KEY:
        try:
            openai_url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt_content}],
                "temperature": 0.8
            }
            headers = HTTP_HEADERS.copy()
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
            req = urllib.request.Request(openai_url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "choices" in data and len(data["choices"]) > 0:
                    return (data["choices"][0]["message"]["content"] if not debug else f"【OpenAI成功】\n{data['choices'][0]['message']['content']}")
        except Exception as e:
            errors.append(f"OpenAI Error: {e}")

    if debug:
        return "❌ API呼出失敗: " + ", ".join(errors)
    return None

async def call_llm(prompt_content, debug=False):
    try:
        return await asyncio.to_thread(_sync_call_llm, prompt_content, debug)
    except Exception as e:
        print(f"[LLM Error]: {e}")
        return None

async def start_5min_timer():
    try:
        await asyncio.sleep(300)
        if game["is_running"] and game["phase"] == "discussion":
            await game["channel"].send("🚨 **【5分経過・議論終了！】** 投票タイムに移ります。")
            await start_voting_phase()
    except asyncio.CancelledError:
        pass

class RoleCountSelectView(discord.ui.View):
    def __init__(self, mode, human_users):
        super().__init__(timeout=300)
        self.mode = mode
        self.human_users = human_users
        self.roles = dict(game["selected_roles"])

    def create_embed(self):
        embed = discord.Embed(
            title="🎴 役職カスタム枚数設定パネル",
            description="ボタンで役職の枚数を増減させてください。（5人プレイ時は合計7枚）",
            color=discord.Color.blue()
        )
        total = 0
        for role, count in self.roles.items():
            emoji = ROLE_EMOJIS.get(role, "")
            embed.add_field(name=f"{emoji} {role}", value=f"**{count}** 枚", inline=True)
            total += count
        embed.set_footer(text=f"現在の合計カード枚数: {total} 枚 (推奨: 7枚)")
        return embed

    @discord.ui.button(label="🐺 人狼+", style=discord.ButtonStyle.danger, row=0)
    async def add_ww(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["人狼"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="人狼-", style=discord.ButtonStyle.secondary, row=0)
    async def sub_ww(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["人狼"] > 0:
            self.roles["人狼"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="👤 市民+", style=discord.ButtonStyle.primary, row=1)
    async def add_cit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["市民"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="市民-", style=discord.ButtonStyle.secondary, row=1)
    async def sub_cit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["市民"] > 0:
            self.roles["市民"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🔮 占い+", style=discord.ButtonStyle.success, row=2)
    async def add_see(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["占い師"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="占い-", style=discord.ButtonStyle.secondary, row=2)
    async def sub_see(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["占い師"] > 0:
            self.roles["占い師"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🕵️ 怪盗+", style=discord.ButtonStyle.success, row=2)
    async def add_thf(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["怪盗"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="怪盗-", style=discord.ButtonStyle.secondary, row=2)
    async def sub_thf(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["怪盗"] > 0:
            self.roles["怪盗"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🎯 狩人+", style=discord.ButtonStyle.success, row=3)
    async def add_hnt(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["狩人"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="狩人-", style=discord.ButtonStyle.secondary, row=3)
    async def sub_hnt(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["狩人"] > 0:
            self.roles["狩人"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="☀️ てる+", style=discord.ButtonStyle.success, row=3)
    async def add_teru(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["てるてる"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="てる-", style=discord.ButtonStyle.secondary, row=3)
    async def sub_teru(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["てるてる"] > 0:
            self.roles["てるてる"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🚀 この構成でゲーム開始！", style=discord.ButtonStyle.blurple, row=4)
    async def confirm_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        total = sum(self.roles.values())
        if total != 7:
            await interaction.response.send_message(f"⚠️ 合計 **7枚** 必要です（現在 {total} 枚）。", ephemeral=True)
            return
        game["selected_roles"] = dict(self.roles)
        await interaction.response.send_message("✨ 構成確定！セットアップ中…", ephemeral=True)
        self.stop()
        await setup_game(interaction.channel, self.mode, self.human_users)

async def setup_game(channel, mode, human_users=None):
    global game
    game["is_running"] = True
    game["mode"] = mode
    game["phase"] = "night"
    game["channel"] = channel
    game["players"] = {}
    game["votes"] = {}
    game["hunter_targets"] = {}
    game["turn_count"] = 0
    game["history"] = []

    human_users = human_users or []
    all_participants = []

    if mode == "watch":
        for ai in AI_CHARACTERS:
            all_participants.append({"name": ai["name"], "is_ai": True, "user_obj": None, "desc": ai["desc"]})
    else:
        for u in human_users:
            all_participants.append({"name": u.display_name, "is_ai": False, "user_obj": u})
        needed = 5 - len(all_participants)
        if needed > 0:
            for ai in random.sample(AI_CHARACTERS, needed):
                all_participants.append({"name": ai["name"], "is_ai": True, "user_obj": None, "desc": ai["desc"]})

    pool = []
    for role, count in game["selected_roles"].items():
        for _ in range(count):
            pool.append(role)

    random.shuffle(pool)
    game["center_cards"] = [pool.pop(), pool.pop()]

    for p in all_participants:
        assigned = pool.pop()
        game["players"][p["name"]] = {
            "is_ai": p["is_ai"],
            "user_obj": p["user_obj"],
            "role": assigned,
            "original_role": assigned,
            "desc": p.get("desc", "")
        }

    if mode == "watch":
        await channel.send("🍿 **観戦モード開始！** `!jinro next` でターン1を開始します。")
    else:
        await channel.send("🌌 **ゲーム開始！** 夜の時間です。DMを確認してください。")

    await process_night_phase()

async def process_night_phase():
    werewolves = [name for name, p in game["players"].items() if p["role"] == "人狼"]

    for name, p in game["players"].items():
        if not p["is_ai"] and p["user_obj"]:
            msg = f"🌙 **役職: 『{p['role']}』**\n"
            if p["role"] == "人狼":
                others = [w for w in werewolves if w != name]
                msg += f"仲間: **{', '.join(others)}**" if others else "（仲間なし）"
            elif p["role"] == "占い師":
                msg += "💬 `!fortune プレイヤー名` または `!fortune 墓場`"
            elif p["role"] == "怪盗":
                msg += "💬 `!steal プレイヤー名`"
            elif p["role"] == "狩人":
                msg += "💬 `!hunt プレイヤー名`"
            try:
                await p["user_obj"].send(msg)
            except Exception as e:
                print(f"[DM失敗]: {e}")

    for name, p in game["players"].items():
        if p["is_ai"]:
            if p["role"] == "占い師":
                t = random.choice([n for n in game["players"].keys() if n != name])
                p["ai_knows"] = f"{t} は『{game['players'][t]['role']}』でした。"
            elif p["role"] == "怪盗":
                t = random.choice([n for n in game["players"].keys() if n != name])
                game["players"][name]["role"], game["players"][t]["role"] = game["players"][t]["role"], game["players"][name]["role"]
                p["ai_knows"] = f"{t} と役職を交換しました。"
            elif p["role"] == "狩人":
                t = random.choice([n for n in game["players"].keys() if n != name])
                game["hunter_targets"][name] = t
                p["ai_knows"] = f"{t} を道連れ指定しました。"
            else:
                p["ai_knows"] = "平穏な夜でした。"

    game["phase"] = "discussion"
    if game["mode"] != "watch":
        await game["channel"].send("☀️ **朝になりました！議論タイム開始 (`!jinro 発言`)**")
        if game["mode"] == "multi":
            game["discussion_task"] = asyncio.create_task(start_5min_timer())
        else:
            await generate_ai_discussion("（議論開始）")

async def generate_ai_discussion(user_input="", is_watch=False):
    if game["phase"] != "discussion":
        return

    game["turn_count"] += 1
    ai_info = []
    for name, p in game["players"].items():
        if p["is_ai"]:
            ai_info.append(f"- {name} ({p['desc']}): 元『{p['original_role']}』, 現在『{p['role']}』. 夜: {p.get('ai_knows', '')}")

    prompt = f"""ワンナイト人狼のAI議論。
ターン: {game['turn_count']} / 5
【AI情報】
{chr(10).join(ai_info)}
【ログ】
{chr(10).join(game['history'][-8:])}
議論のやり取りを出力してください。"""

    try:
        async with game["channel"].typing():
            reply = await call_llm(prompt)
            if reply:
                if user_input:
                    game["history"].append(f"人間発言: {user_input}")
                game["history"].append(reply)
                header = f"🗣️ **【ターン {game['turn_count']} / 5】**\n" if is_watch else ""
                await send_split_message(game["channel"], header + reply)
    except Exception as e:
        print(f"[議論エラー]: {e}")

    if game["turn_count"] >= 5:
        await game["channel"].send("\n🚨 **5ターン終了！投票タイムへ移行します。**")
        await start_voting_phase()

async def start_voting_phase():
    game["phase"] = "voting"
    await game["channel"].send("🗳️ **投票タイム**（DMで `!vote プレイヤー名`）")
    for name, p in game["players"].items():
        if p["is_ai"]:
            game["votes"][name] = random.choice([n for n in game["players"].keys() if n != name])
    if len([n for n, p in game["players"].items() if not p["is_ai"]]) == 0:
        await asyncio.sleep(2)
        await Tally_and_finish()

async def Tally_and_finish():
    game["phase"] = "ended"
    game["is_running"] = False
    if game["discussion_task"]:
        game["discussion_task"].cancel()

    counts = {}
    for v, t in game["votes"].items():
        counts[t] = counts.get(t, 0) + 1

    max_v = max(counts.values()) if counts else 0
    executed = [n for n, c in counts.items() if c == max_v]

    res = "⚖️ **集計結果**\n"
    for v, t in game["votes"].items():
        res += f"・{v} ➡️ {t}\n"

    exec_p = None
    drag_p = None
    if len(executed) == 1:
        exec_p = executed[0]
        res += f"\n🩸 最多得票: **{exec_p}** が処刑されました！\n"
        if game["players"][exec_p]["role"] == "狩人" and exec_p in game["hunter_targets"]:
            drag_p = game["hunter_targets"][exec_p]
            res += f"🎯 **狩人の道連れ発動！** ➡️ **{drag_p}** を巻き添えにしました！\n"
    else:
        res += "\n🩸 票が割れたため平和村となりました。\n"

    res += "\n🎉 **勝敗発表**\n"
    if (exec_p and game["players"][exec_p]["role"] == "てるてる") or (drag_p and game["players"][drag_p]["role"] == "てるてる"):
        res += "☀️ **てるてる坊主の単独勝利！**\n"
    else:
        w_win, w_lose = False, False
        if exec_p and game["players"][exec_p]["role"] == "狩人" and drag_p:
            if game["players"][drag_p]["role"] == "人狼":
                w_win = True
            else:
                w_lose = True

        if w_win:
            res += "🏆 **市民陣営の勝利！**（狩人が人狼を道連れ）\n"
        elif w_lose:
            res += "🐺 **人狼陣営の勝利！**（狩人が村人を道連れ）\n"
        elif exec_p and game["players"][exec_p]["role"] == "人狼":
            res += "🏆 **市民陣営の勝利！**\n"
        else:
            res += "🐺 **人狼陣営の勝利！**\n"

    res += "\n📜 **最終正解**\n"
    for n, p in game["players"].items():
        res += f"・{n}: 『{p['role']}』\n"
    res += f"・墓場: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』\n"

    await send_split_message(game["channel"], res)
