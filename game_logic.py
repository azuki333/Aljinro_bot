import discord, urllib.request, urllib.error, json, asyncio, os, random

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
HTTP_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

# ── 5人のAIの性格付け（個別設定） ──
AI_CHARACTERS = [
    {"name": "アル", "desc": "20代男性。冷静な論理派。客観的なデータと事実を元に、矛盾のない綺麗な推理を組み立てる。"},
    {"name": "レイ", "desc": "25歳男性。冷静な策士。表向きは普通に見せかけつつ、裏で盤面をコントロールしようとする。"},
    {"name": "ジン", "desc": "22歳男性。大胆な議論派。自分の意見をハッキリ主張し、議論の雰囲気をグイグイ引っ張る。"},
    {"name": "シェスタ", "desc": "19歳女性。社交的な議論派。場を和ませつつ、上手に他の人から情報を引き出すのが得意。"},
    {"name": "ルナ", "desc": "24歳女性。心理戦が得意な策士。あえて嘘（ブラフ）を混ぜたり、相手の反応を面白がる。"}
]

ROLE_EMOJIS = {
    "人狼": "🐺", "市民": "👤", "占い師": "🔮", "怪盗": "🕵️", 
    "狩人": "🎯", "てるてる": "☀️", "魔女っ子": "🧙‍♀️", "狂人": "🤫"
}

game = {
    "is_running": False, "mode": None, "phase": "idle", "channel": None,
    "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {},
    "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
    "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0},
    "watch_turn_index": 0
}

def reset_game_state():
    global game
    if game["discussion_task"]: game["discussion_task"].cancel()
    game.clear()
    game.update({
        "is_running": False, "mode": None, "phase": "idle", "channel": None,
        "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {},
        "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
        "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0},
        "watch_turn_index": 0
    })

async def send_split_message(channel, content):
    if not content or not channel: return
    for i in range(0, len(content), 1900):
        try: await channel.send(content[i:i+1900])
        except Exception as e: print(f"[送信エラー]: {e}")

def _sync_call_llm(prompt_content, debug=False):
    errors = []
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt_content}]}]}
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=HTTP_HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "candidates" in data and len(data["candidates"]) > 0:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    if len(text) > 5: return (text if not debug else f"【Gemini成功】\n{text}")
        except Exception as e: errors.append(f"Gemini Error: {e}")

    if OPENAI_API_KEY:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt_content}], "temperature": 0.8}
            headers = HTTP_HEADERS.copy()
            headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "choices" in data and len(data["choices"]) > 0:
                    return (data["choices"][0]["message"]["content"] if not debug else f"【OpenAI成功】\n{data['choices'][0]['message']['content']}")
        except Exception as e: errors.append(f"OpenAI Error: {e}")

    return "❌ API呼出失敗: " + ", ".join(errors) if debug else None

async def call_llm(prompt_content, debug=False):
    try: return await asyncio.to_thread(_sync_call_llm, prompt_content, debug)
    except Exception as e: print(f"[LLM Error]: {e}"); return None

async def generate_ai_discussion(is_watch=False, user_input=None):
    ai_players_list = [p for p in game["players"].values() if p["is_ai"]]
    if not ai_players_list: return
    ai_p = random.choice(ai_players_list)
    char_info = ai_p.get("ai_char", {"name": ai_p["name"], "desc": "普通のAIプレイヤー"})
    
    prompt = f"""
あなたはワンナイト人狼のAIプレイヤーです。
キャラクター設定: {char_info['name']} - {char_info['desc']}
あなたの本当の役職: {ai_p['role']}
これまでの状況: {json.dumps(game['history'][-5:], ensure_ascii=False)}
{f"直前のプレイヤーの発言: {user_input}" if user_input else ""}
会話のトーンを守り、短く自然な日本語で1つ発言してください（2文以内）。名前は不要です。
"""
    res = await call_llm(prompt)
    if res and game["channel"]:
        await send_split_message(game["channel"], f"💬 **{ai_p['name']}**: {res}")
        game["history"].append(f"{ai_p['name']}: {res}")
    return res

async def step_watch_discussion(channel):
    if not game["is_running"] or game["mode"] != "watch":
        await channel.send("⚠️ 現在、観戦モードが進行中ではありません。")
        return

    if game["phase"] != "discussion":
        await channel.send("⚠️ 現在は議論フェイズではありません。")
        return

    ai_players = [p for p in game["players"].values() if p["is_ai"]]
    max_turns = 5

    if game["watch_turn_index"] < max_turns:
        current_turn = game["watch_turn_index"] + 1
        ai_p = ai_players[game["watch_turn_index"] % len(ai_players)]
        char_info = ai_p.get("ai_char", {"name": ai_p["name"], "desc": "普通のAI"})
        
        prompt = f"""
あなたはワンナイト人狼のAIプレイヤーです（観戦モード・第{current_turn}ターン目）。
キャラクター設定: {char_info['name']} - {char_info['desc']}
あなたの本当の役職: {ai_p['role']}
これまでの状況: {json.dumps(game['history'][-5:], ensure_ascii=False)}
会話のトーンを守り、短く自然な日本語で1つ発言してください（2文以内）。名前は不要です。
"""
        res = await call_llm(prompt)
        if res:
            await send_split_message(channel, f"💬 **[第{current_turn}/5ターン] {ai_p['name']}**: {res}")
            game["history"].append(f"{ai_p['name']}: {res}")

        game["watch_turn_index"] += 1

        if game["watch_turn_index"] >= max_turns:
            await channel.send("✨ **5ターンの議論が終了しました！** `!jinro next` をもう一度打つと投票・結果発表に進みます。")
    else:
        await channel.send("🗳️ **投票フェイズに移行します...**")
        for p in ai_players:
            targets = [n for n in game["players"].keys() if n != p["name"]]
            game["votes"][p["name"]] = random.choice(targets)
        await Tally_and_finish()

async def start_5min_timer():
    try:
        await asyncio.sleep(300)
        if game["is_running"] and game["phase"] == "discussion":
            await game["channel"].send("🚨 **【5分経過・議論終了！】** 投票タイムに移ります。")
            await start_voting_phase()
    except asyncio.CancelledError: pass

# --- 役職カスタムView ---
class RoleCountSelectView(discord.ui.View):
    def __init__(self, mode, human_users):
        super().__init__(timeout=300)
        self.mode = mode
        self.human_users = human_users or []
        self.roles = dict(game["selected_roles"])

    def create_embed(self):
        embed = discord.Embed(
            title="🎴 役職カスタム枚数設定", 
            description="ボタンで各役職の枚数を増減できます（5人プレイ時は合計7枚にしてください）。", 
            color=discord.Color.blue()
        )
        total = sum(self.roles.values())
        for r, c in self.roles.items(): 
            embed.add_field(name=f"{ROLE_EMOJIS.get(r,'')} {r}", value=f"**{c}**枚", inline=True)
        embed.set_footer(text=f"現在の合計枚数: {total}枚 (推奨: 7枚)")
        return embed

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🐺 人狼+", style=discord.ButtonStyle.danger, row=0)
    async def add_werewolf(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["人狼"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="🐺 人狼-", style=discord.ButtonStyle.secondary, row=0)
    async def sub_werewolf(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["人狼"] > 0: self.roles["人狼"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="👤 市民+", style=discord.ButtonStyle.primary, row=0)
    async def add_citizen(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["市民"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="👤 市民-", style=discord.ButtonStyle.secondary, row=0)
    async def sub_citizen(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["市民"] > 0: self.roles["市民"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="🔮 占い+", style=discord.ButtonStyle.success, row=1)
    async def add_seer(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["占い師"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="🔮 占い-", style=discord.ButtonStyle.secondary, row=1)
    async def sub_seer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["占い師"] > 0: self.roles["占い師"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="🕵️ 怪盗+", style=discord.ButtonStyle.success, row=1)
    async def add_thief(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["怪盗"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="🕵️ 怪盗-", style=discord.ButtonStyle.secondary, row=1)
    async def sub_thief(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["怪盗"] > 0: self.roles["怪盗"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="🎯 狩人+", style=discord.ButtonStyle.primary, row=2)
    async def add_hunter(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["狩人"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="🎯 狩人-", style=discord.ButtonStyle.secondary, row=2)
    async def sub_hunter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["狩人"] > 0: self.roles["狩人"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="☀️ てル+", style=discord.ButtonStyle.primary, row=2)
    async def add_teru(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["てるてる"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="☀️ てル-", style=discord.ButtonStyle.secondary, row=2)
    async def sub_teru(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["てるてる"] > 0: self.roles["てるてる"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="🧙 魔女+", style=discord.ButtonStyle.primary, row=3)
    async def add_witch(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["魔女っ子"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="🧙 魔女-", style=discord.ButtonStyle.secondary, row=3)
    async def sub_witch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["魔女っ子"] > 0: self.roles["魔女っ子"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="🤫 狂人+", style=discord.ButtonStyle.danger, row=3)
    async def add_mad(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["狂人"] += 1
        await self.update_message(interaction)

    @discord.ui.button(label="🤫 狂人-", style=discord.ButtonStyle.secondary, row=3)
    async def sub_mad(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["狂人"] > 0: self.roles["狂人"] -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="🚀 この設定でゲーム開始！", style=discord.ButtonStyle.blurple, row=4)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if sum(self.roles.values()) != 7:
            await interaction.response.send_message("⚠️ 役職の合計枚数は7枚にしてください（プレイヤー5人＋中央2枚）。", ephemeral=True)
            return
        await interaction.response.send_message("✨ セットアップ中...", ephemeral=True)
        game["selected_roles"] = dict(self.roles)
        self.stop()
        
        users = self.human_users if self.human_users else [interaction.user]
        asyncio.create_task(setup_game(interaction.channel, self.mode, users))

# --- ワンナイト人狼セットアップ ---
async def setup_game(channel, mode="solo", human_users=None):
    reset_game_state()
    game["is_running"] = True
    game["mode"] = mode
    game["phase"] = "night"
    game["channel"] = channel

    human_users = human_users or []

    if mode == "watch":
        player_names = [c["name"] for c in AI_CHARACTERS]
    elif mode == "solo":
        human_user = human_users[0] if len(human_users) > 0 else None
        human_name = human_user.display_name if human_user else "あなた"
        player_names = [human_name] + [c["name"] for c in AI_CHARACTERS]
    else:
        player_names = [u.display_name for u in human_users] + [c["name"] for c in AI_CHARACTERS]

    pool = []
    for r, count in game["selected_roles"].items():
        pool.extend([r] * count)
    random.shuffle(pool)

    available_ai_chars = list(AI_CHARACTERS)
    random.shuffle(available_ai_chars)

    for i, name in enumerate(player_names):
        if mode == "watch":
            is_ai = True
            user_obj = None
            ai_info = available_ai_chars.pop(0)
        elif mode == "solo":
            is_ai = (i > 0)
            user_obj = human_users[0] if (not is_ai and len(human_users) > 0) else None
            ai_info = available_ai_chars.pop(0) if is_ai else None
        else:
            is_ai = (i >= len(human_users))
            user_obj = human_users[i] if (not is_ai and i < len(human_users)) else None
            ai_info = available_ai_chars.pop(0) if is_ai else None

        game["players"][name] = {
            "name": name,
            "role": pool[i],
            "original_role": pool[i],
            "is_ai": is_ai,
            "user": user_obj,
            "ai_char": ai_info,
            "alive": True
        }

    game["center_cards"] = [pool[len(player_names)], pool[len(player_names)+1]]
    game["turn_count"] = 1

    if mode == "watch":
        await channel.send("👀 **観戦モード開始**：AIたちによるワンナイト人狼を開始します。\n👉 `!jinro next` を打つと、1ターンずつ議論が進みます（全5ターン）。")
    else:
        await channel.send("🌙 **夜が訪れました…プレイヤー全員の役職が配られました。**\n各自、自身の役職をDMで確認してください。")
        for p in game["players"].values():
            if not p["is_ai"] and p["user"]:
                try:
                    dm_channel = await p["user"].create_dm()
                    role_name = p["role"]
                    emoji = ROLE_EMOJIS.get(role_name, "")
                    await dm_channel.send(
                        f"🌙 **ワンナイト人狼が始まりました！**\n"
                        f"あなたの役職は **{emoji} {role_name}** です。\n\n"
                        f"能力コマンド例:\n"
                        f"- 占い師: `!fortune [プレイヤー名 / 墓場]`\n"
                        f"- 怪盗: `!steal [プレイヤー名]`\n"
                        f"- 狩人: `!hunt [プレイヤー名]`\n"
                        f"- 魔女っ子: `!witch [プレイヤー名]`"
                    )
                except Exception as e:
                    print(f"[DM送信エラー] {e}")
                    await channel.send(f"⚠️ {p['user'].mention} へのDM送信に失敗しました。")

    await asyncio.sleep(3)
    await process_night_phase(channel)

async def process_night_phase(channel):
    game["phase"] = "night"
    await channel.send("🔮 **【夜の行動フェイズ】** 各種役職が能力を使用しています...")
    await asyncio.sleep(3)
    await start_discussion_phase(channel)

async def start_discussion_phase(channel):
    game["phase"] = "discussion"
    if game["mode"] == "watch":
        await channel.send("☀️ **朝になりました（観戦モード）！** `!jinro next` を打って議論を進めてください。")
    else:
        await channel.send("☀️ **朝になりました！これより議論を開始します。**（制限時間：5分、または投票へ）")
        game["discussion_task"] = asyncio.create_task(start_5min_timer())
        asyncio.create_task(ai_chatter_loop(channel))

async def ai_chatter_loop(channel):
    try:
        while game["is_running"] and game["phase"] == "discussion" and game["mode"] != "watch":
            await asyncio.sleep(random.randint(25, 40))
            if not game["is_running"] or game["phase"] != "discussion": break
            await generate_ai_discussion(is_watch=False)
    except asyncio.CancelledError: pass

async def start_voting_phase():
    if game["phase"] == "voting": return
    game["phase"] = "voting"
    if game["discussion_task"]: game["discussion_task"].cancel()
    
    embed = discord.Embed(title="🗳️ 投票タイム", description="誰を生け贄（人狼）として処刑するか投票してください！", color=discord.Color.gold())
    await game["channel"].send(embed=embed)

async def Tally_and_finish():
    game["phase"] = "result"
    if game["discussion_task"]: game["discussion_task"].cancel()
    await game["channel"].send("⚖️ **投票が締め切られました！結果を集計します...**")
    await asyncio.sleep(2)

    counts = {}
    for target in game["votes"].values():
        counts[target] = counts.get(target, 0) + 1
    
    max_votes = max(counts.values()) if counts else 0
    executed = [name for name, c in counts.items() if c == max_votes]

    result_desc = "### 📊 投票結果\n"
    for v, t in game["votes"].items():
        result_desc += f"- {v} ➔ 投票先: **{t}**\n"

    werewolves = [p["name"] for p in game["players"].values() if p["role"] == "人狼"]
    winner = "市民チームの勝利！" if any(e in werewolves for e in executed) else "人狼チームの勝利！"

    result_desc += f"\n🏆 **勝敗結果**: {winner}\n\n### 🎴 最終的な役職公開\n"
    for p in game["players"].values():
        result_desc += f"- **{p['name']}**: {ROLE_EMOJIS.get(p['role'],'')} {p['role']} (初期役職: {p['original_role']})\n"

    embed = discord.Embed(title="🎉 ゲーム終了 - ワンナイト人狼", description=result_desc, color=discord.Color.green())
    await game["channel"].send(embed=embed)
    reset_game_state()
