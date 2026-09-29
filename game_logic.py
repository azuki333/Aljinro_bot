import discord, urllib.request, urllib.error, json, asyncio, os, random

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
HTTP_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

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
    "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0}
}

def reset_game_state():
    global game
    if game["discussion_task"]: game["discussion_task"].cancel()
    game.clear()
    game.update({
        "is_running": False, "mode": None, "phase": "idle", "channel": None,
        "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {},
        "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
        "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0}
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

async def start_5min_timer():
    try:
        await asyncio.sleep(300)
        if game["is_running"] and game["phase"] == "discussion":
            await game["channel"].send("🚨 **【5分経過・議論終了！】** 投票タイムに移ります。")
            await start_voting_phase()
    except asyncio.CancelledError: pass

class RoleCountSelectView(discord.ui.View):
    def __init__(self, mode, human_users):
        super().__init__(timeout=300)
        self.mode = mode
        self.human_users = human_users
        self.roles = dict(game["selected_roles"])

    def create_embed(self):
        embed = discord.Embed(title="🎴 役職カスタム枚数設定", description="5人プレイ時は合計7枚にしてください。", color=discord.Color.blue())
        total = sum(self.roles.values())
        for r, c in self.roles.items(): embed.add_field(name=f"{ROLE_EMOJIS.get(r,'')} {r}", value=f"**{c}**枚", inline=True)
        embed.set_footer(text=f"合計枚数: {total}枚 (推奨: 7枚)")
        return embed

    @discord.ui.button(label="🐺 人狼+", style=discord.ButtonStyle.danger, row=0)
    async def a_ww(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["人狼"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="人狼-", style=discord.ButtonStyle.secondary, row=0)
    async def s_ww(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["人狼"] > 0: self.roles["人狼"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="👤 市民+", style=discord.ButtonStyle.primary, row=0)
    async def a_cit(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["市民"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="市民-", style=discord.ButtonStyle.secondary, row=0)
    async def s_cit(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["市民"] > 0: self.roles["市民"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🔮 占い+", style=discord.ButtonStyle.success, row=1)
    async def a_see(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["占い師"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="占い-", style=discord.ButtonStyle.secondary, row=1)
    async def s_see(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["占い師"] > 0: self.roles["占い師"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🕵️ 怪盗+", style=discord.ButtonStyle.success, row=1)
    async def a_thf(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["怪盗"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="怪盗-", style=discord.ButtonStyle.secondary, row=1)
    async def s_thf(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["怪盗"] > 0: self.roles["怪盗"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🎯 狩人+", style=discord.ButtonStyle.success, row=2)
    async def a_hnt(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["狩人"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="狩人-", style=discord.ButtonStyle.secondary, row=2)
    async def s_hnt(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["狩人"] > 0: self.roles["狩人"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="☀️ てる+", style=discord.ButtonStyle.success, row=2)
    async def a_teru(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["てるてる"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="てる-", style=discord.ButtonStyle.secondary, row=2)
    async def s_teru(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["てるてる"] > 0: self.roles["てるてる"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🧙 魔女+", style=discord.ButtonStyle.success, row=3)
    async def a_witch(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["魔女っ子"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="魔女-", style=discord.ButtonStyle.secondary, row=3)
    async def s_witch(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["魔女っ子"] > 0: self.roles["魔女っ子"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🤫 狂人+", style=discord.ButtonStyle.success, row=3)
    async def a_mad(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(); self.roles["狂人"] += 1; await i.edit_original_response(embed=self.create_embed(), view=self)
    @discord.ui.button(label="狂人-", style=discord.ButtonStyle.secondary, row=3)
    async def s_mad(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer();
        if self.roles["狂人"] > 0: self.roles["狂人"] -= 1
        await i.edit_original_response(embed=self.create_embed(), view=self)

    @discord.ui.button(label="🚀 ゲーム開始！", style=discord.ButtonStyle.blurple, row=4)
    async def confirm(self, i: discord.Interaction, b: discord.ui.Button):
        if sum(self.roles.values()) != 7:
            await i.response.send_message("⚠️ 合計7枚にしてください。", ephemeral=True); return
        await i.response.send_message("✨ セットアップ中...", ephemeral=True)
        game["selected_roles"] = dict(self.roles)
        self.stop()
        asyncio.create_task(setup_game(i.channel, self.mode, self.human_users))
async def setup_game(channel, mode, human_users):
    reset_game_state()
    game["is_running"] = True
    game["mode"] = mode
    game["phase"] = "night"
    game["channel"] = channel

    names = ["あなた"] + [c["name"] for c in AI_CHARACTERS] if mode == "solo" else [u.display_name for u in human_users] + [c["name"] for c in AI_CHARACTERS]
    selected_ai_chars = list(AI_CHARACTERS)
    random.shuffle(selected_ai_chars)

    pool = []
    for r, count in game["selected_roles"].items():
        pool.extend([r] * count)
    random.shuffle(pool)

    for i, name in enumerate(names):
        is_ai = (i > 0) if mode == "solo" else (i >= len(human_users))
        user_obj = human_users[0] if mode == "solo" and i == 0 else (human_users[i] if not is_ai else None)
        ai_info = selected_ai_chars.pop(0) if is_ai else None

        game["players"][name] = {
            "name": name, "role": pool[i], "original_role": pool[i],
            "is_ai": is_ai, "user": user_obj, "ai_char": ai_info, "alive": True
        }

    game["center_cards"] = [pool[len(names)], pool[len(names)+1]]
    game["turn_count"] = 1

    await channel.send("🌙 **夜が訪れました…プレイヤー全員の役職が配られました。**\n各自、自身の役職を確認してください。（まもなく夜の行動フェイズに入ります）")
    await asyncio.sleep(4)
    await process_night_phase(channel)

async def process_night_phase(channel):
    game["phase"] = "night"
    await channel.send("🔮 **【夜の行動：占い師・怪盗・狩人・魔女】**\nそれぞれの能力者が自動で行動しています...")

    # 占い師の処理
    seer = next((p for p in game["players"].values() if p["original_role"] == "占い師"), None)
    if seer:
        targets = [n for n, p in game["players"].items() if n != seer["name"]]
        if targets:
            chosen = random.choice(targets)
            c_role = game["players"][chosen]["original_role"]
            res_text = f"🔮 【占い結果】{chosen}の役職は **{c_role}** です。"
            if not seer["is_ai"] and seer["user"]:
                try: await seer["user"].send(res_text)
                except: await channel.send(f"(DM送信失敗のためパブリックに通知) {res_text}")
            game["history"].append(f"占い師({seer['name']})が{chosen}を占い、{c_role}と知った。")

    # 怪盗の処理
    thief = next((p for p in game["players"].values() if p["original_role"] == "怪盗"), None)
    if thief:
        targets = [n for n, p in game["players"].items() if n != thief["name"]]
        if targets:
            chosen = random.choice(targets)
            thief_role = thief["role"]
            target_role = game["players"][chosen]["role"]
            game["players"][thief["name"]]["role"] = target_role
            game["players"][chosen]["role"] = thief_role
            res_text = f"🕵️ 【怪盗スキル発動】あなたは {chosen} から **{target_role}** を盗みました！"
            if not thief["is_ai"] and thief["user"]:
                try: await thief["user"].send(res_text)
                except: pass
            game["history"].append(f"怪盗({thief['name']})が{chosen}と役職を交換した。")

    await asyncio.sleep(3)
    await start_discussion_phase(channel)

async def start_discussion_phase(channel):
    game["phase"] = "discussion"
    await channel.send("☀️ **朝になりました！これより議論を開始します。**（制限時間：5分、または「/vote」で投票へ）\nAIキャラクターたちも発言を始めます。")
    game["discussion_task"] = asyncio.create_task(start_5min_timer())
    asyncio.create_task(ai_chatter_loop(channel))

async def ai_chatter_loop(channel):
    try:
        while game["is_running"] and game["phase"] == "discussion":
            await asyncio.sleep(random.randint(25, 40))
            if not game["is_running"] or game["phase"] != "discussion": break
            ai_p = random.choice([p for p in game["players"].values() if p["is_ai"]])
            prompt = f"""
あなたはワンナイト人狼のAIプレイヤーです。
キャラクター設定: {ai_p['ai_char']['name']} - {ai_p['ai_char']['desc']}
あなたの本当の役職: {ai_p['role']}
これまでの状況: {json.dumps(game['history'][-5:], ensure_ascii=False)}
会話のトーンを守り、短く自然な日本語で1つ発言してください（2文以内、役職を勝手に明かすかは自由）。名前は不要です。
"""
            res = await call_llm(prompt)
            if res:
                await send_split_message(channel, f"💬 **{ai_p['name']}**: {res}")
                game["history"].append(f"{ai_p['name']}: {res}")
    except asyncio.CancelledError: pass

async def start_voting_phase():
    if game["phase"] == "voting": return
    game["phase"] = "voting"
    if game["discussion_task"]: game["discussion_task"].cancel()
    
    embed = discord.Embed(title="🗳️ 投票タイム", description="誰を生け贄（人狼）として処刑するか投票してください！", color=discord.Color.gold())
    view = VoteView()
    await game["channel"].send(embed=embed, view=view)

class VoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        for name in game["players"].keys():
            self.add_item(VoteButton(name))

class VoteButton(discord.ui.Button):
    def __init__(self, target_name):
        super().__init__(label=target_name, style=discord.ButtonStyle.secondary)
        self.target_name = target_name

    async def callback(self, i: discord.Interaction):
        voter = i.user.display_name
        game["votes"][voter] = self.target_name
        await i.response.send_message(f"✅ **{self.target_name}** に投票しました。", ephemeral=True)
        
        # 全員投票完了したかチェック（人間＋AI簡易自動投票）
        ai_voters = [p["name"] for p in game["players"].values() if p["is_ai"] and p["name"] not in game["votes"]]
        for av in ai_voters:
            targets = [n for n in game["players"].keys() if n != av]
            game["votes"][av] = random.choice(targets)

        if len(game["votes"]) >= len(game["players"]):
            self.view.stop()
            await finalize_game(i.channel)

async def finalize_game(channel):
    game["phase"] = "result"
    await channel.send("⚖️ **全員の投票が完了しました！結果を集計します...**")
    await asyncio.sleep(2)

    # 投票集計
    counts = {}
    for target in game["votes"].values():
        counts[target] = counts.get(target, 0) + 1
    
    max_votes = max(counts.values()) if counts else 0
    executed = [name for name, c in counts.items() if c == max_votes]

    result_desc = "### 📊 投票結果\n"
    for v, t in game["votes"].items():
        result_desc += f"- {v} ➔ 投票先: **{t}**\n"

    # 勝敗判定ロジック
    # 簡易判定：人狼が処刑されたか？
    werewolves = [p["name"] for p in game["players"].values() if p["role"] == "人狼"]
    winner = "市民チームの勝利！" if any(e in werewolves for e in executed) else "人狼チームの勝利！"

    result_desc += f"\n🏆 **勝敗結果**: {winner}\n\n### 🎴 最終的な役職公開\n"
    for p in game["players"].values():
        result_desc += f"- **{p['name']}**: {ROLE_EMOJIS.get(p['role'],'')} {p['role']} (初期役職: {p['original_role']})\n"

    embed = discord.Embed(title="🎉 游戏終了 - ワンナイト人狼", description=result_desc, color=discord.Color.green())
    await channel.send(embed=embed)
    reset_game_state()

# Bot起動用コード等 (環境に合わせて設定)        
