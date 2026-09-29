import discord, urllib.request, urllib.error, json, asyncio, os, random

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
HTTP_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

AI_CHARACTERS = [
    {"name": "レン", "desc": "20代男性。冷静沈着で論理的。矛盾や怪しい発言を見逃さず詰めるタイプ。"},
    {"name": "ユイ", "desc": "17歳女子高生。直感重視で天然だが直感が当たる。"},
    {"name": "Gemini-A", "desc": "確率とログ分析重視の分析派。"},
    {"name": "Gemini-B", "desc": "心理戦が得意なブラフ担当。"},
    {"name": "タクミ", "desc": "30代ベテラン。盤面を乱して様子を見る戦略派。"}
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

async def setup_game(channel, mode, human_users=None):
    global game
    game.update({
        "is_running": True, "mode": mode, "phase": "night", "channel": channel,
        "players": {}, "votes": {}, "hunter_targets": {}, "witch_targets": {},
        "turn_count": 0, "history": []
    })
    human_users = human_users or []
    
    if mode == "watch":
        parts = [{"name": ai["name"], "is_ai": True, "desc": ai["desc"]} for ai in AI_CHARACTERS]
    else:
        parts = [{"name": u.display_name, "is_ai": False, "user_obj": u} for u in human_users] + \
                [{"name": ai["name"], "is_ai": True, "desc": ai["desc"]} for ai in random.sample(AI_CHARACTERS, 5 - len(human_users))]

    pool = []
    for r, c in game["selected_roles"].items():
        pool.extend([r] * c)
    random.shuffle(pool)
    
    game["center_cards"] = [pool.pop(), pool.pop()]
    for p in parts:
        role = pool.pop()
        game["players"][p["name"]] = {
            "is_ai": p["is_ai"], "user_obj": p.get("user_obj"),
            "role": role, "original_role": role, "desc": p.get("desc", "")
        }

    if mode == "watch":
        await channel.send("🍿 **観戦モード開始！** `!jinro next` で次のターンへ進みます。")
    else:
        await channel.send("🌌 **ゲーム開始！** 夜の時間です。DMを確認してください。")
    await process_night_phase()

async def process_night_phase():
    wws = [n for n, p in game["players"].items() if p["role"] == "人狼"]
    for n, p in game["players"].items():
        if not p["is_ai"] and p["user_obj"]:
            msg = f"🌙 **役職: 『{p['role']}』**\n"
            if p["role"] == "人狼":
                msg += f"仲間: {', '.join([w for w in wws if w != n]) or 'なし（または墓場にいます）'}"
            elif p["role"] == "占い師":
                msg += "💬 占うには `!fortune プレイヤー名` または `!fortune 墓場`"
            elif p["role"] == "怪盗":
                msg += "💬 盗むには `!steal プレイヤー名`"
            elif p["role"] == "狩人":
                msg += "💬 道連れを指定するには `!hunt プレイヤー名`"
            elif p["role"] == "魔女っ子":
                msg += "💬 覗き見るには `!witch プレイヤー名`"
            else:
                msg += "今夜は静かに眠りましょう。"
            try:
                await p["user_obj"].send(msg)
            except:
                pass

    for n, p in game["players"].items():
        if p["is_ai"]:
            if p["role"] == "占い師":
                t = random.choice([k for k in game["players"] if k != n])
                p["ai_knows"] = f"{t} は『{game['players'][t]['role']}』でした。"
            elif p["role"] == "怪盗":
                t = random.choice([k for k in game["players"] if k != n])
                game["players"][n]["role"], game["players"][t]["role"] = game["players"][t]["role"], game["players"][n]["role"]
                p["ai_knows"] = f"{t} と役職を交換しました。"
            elif p["role"] == "狩人":
                t = random.choice([k for k in game["players"] if k != n])
                game["hunter_targets"][n] = t
                p["ai_knows"] = f"{t} を道連れ指定しました。"
            elif p["role"] == "魔女っ子":
                t = random.choice([k for k in game["players"] if k != n])
                game["witch_targets"][n] = t
                p["ai_knows"] = f"{t} の役職は『{game['players'][t]['role']}』でした。"
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
    if game["phase"] != "discussion": return
    game["turn_count"] += 1
    ai_info = [f"- {n}: 設定({p['desc']}), 役職({p['role']}), 夜行動({p.get('ai_knows','')})" for n, p in game["players"].items() if p["is_ai"]]
    prompt = f"ワンナイト人狼AI議論（ターン{game['turn_count']}/5）。嘘やブラフも交えて議論してください。\n【AI一覧】\n" + "\n".join(ai_info) + f"\n【ログ】\n" + "\n".join(game["history"][-10:]) + f"\n【発言】\n{user_input or '（なし）'}"
    
    try:
        async with game["channel"].typing():
            reply = await call_llm(prompt)
            if reply:
                if user_input: game["history"].append(f"人間発言: {user_input}")
                game["history"].append(reply)
                await send_split_message(game["channel"], (f"🗣️ **【ターン {game['turn_count']} / 5】**\n" if is_watch else "") + reply)
    except Exception as e:
        print(f"[議論エラー]: {e}")

    if game["turn_count"] >= 5:
        await game["channel"].send("\n🚨 **5ターン終了！投票タイムへ移行します。**")
        await start_voting_phase()

async def start_voting_phase():
    game["phase"] = "voting"
    await game["channel"].send("🗳️ **投票タイム**（DMで `!vote プレイヤー名` と送信してください）")
    for n, p in game["players"].items():
        if p["is_ai"]:
            game["votes"][n] = random.choice([k for k in game["players"] if k != n])
    if len([n for n, p in game["players"].items() if not p["is_ai"]]) == 0:
        await asyncio.sleep(2)
        await Tally_and_finish()

async def Tally_and_finish():
    game["phase"] = "ended"
    game["is_running"] = False
    if game["discussion_task"]: game["discussion_task"].cancel()

    counts = {}
    for v, t in game["votes"].items():
        counts[t] = counts.get(t, 0) + 1

    res = "⚖️ **集計結果**\n"
    for v, t in game["votes"].items():
        res += f"・{v} ➡️ {t}\n"

    exec_p, drag_p = None, None
    if not game["votes"] or len(counts) == 0:
        res += "\n🩸 誰も投票しなかったため、平和村となりました。\n"
    else:
        max_v = max(counts.values()) if counts else 0
        executed_candidates = [n for n, c in counts.items() if c == max_v]

        if len(executed_candidates) == 1:
            exec_p = executed_candidates[0]
            res += f"\n🩸 最多得票: **{exec_p}** が処刑されました！\n"
        else:
            exec_p = random.choice(executed_candidates)
            res += f"\n🩸 最高得票（{max_v}票）で並んだ [{', '.join(executed_candidates)}] の中から、抽選の結果 **{exec_p}** が処刑されました！\n"

        if exec_p and game["players"][exec_p]["role"] == "狩人" and exec_p in game["hunter_targets"]:
            drag_p = game["hunter_targets"][exec_p]
            res += f"🎯 **狩人の道連れ発動！** ➡️ **{drag_p}** を巻き添えにしました！\n"

    res += "\n🎉 **勝敗発表**\n"
    if not exec_p:
        res += "🐺 **人狼陣営の勝利！**（処刑者なし・平和村）\n"
    elif (exec_p and game["players"][exec_p]["role"] == "てるてる") or (drag_p and game["players"][drag_p]["role"] == "てるてる"):
        res += "☀️ **てるてる坊主の単独勝利！**\n"
    else:
        w_win, w_lose = False, False
        if exec_p and game["players"][exec_p]["role"] == "狩人" and drag_p:
            if game["players"][drag_p]["role"] == "人狼": w_win = True
            else: w_lose = True

        if w_win: res += "🏆 **市民陣営の勝利！**（狩人が人狼を道連れ）\n"
        elif w_lose: res += "🐺 **人狼陣営の勝利！**（狩人が市民を道連れ）\n"
        elif exec_p and game["players"][exec_p]["role"] == "人狼": res += "🏆 **市民陣営の勝利！**\n"
        else: res += "🐺 **人狼陣営の勝利！**\n"

    res += "\n📜 **最終正解**\n"
    for n, p in game["players"].items():
        res += f"・{n}: 『{p['role']}』\n"
    res += f"・墓場: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』\n"
    await send_split_message(game["channel"], res)
