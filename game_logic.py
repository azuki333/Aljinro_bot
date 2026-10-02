import discord
import urllib.request
import json
import asyncio
import os
import random

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
HTTP_HEADERS = {"Content-Type": "application/json"}

AI_CHARACTERS = [
    {"name": "アル", "desc": "20代男性。冷静な論理派。客観的なデータと事実を元に、矛盾のない綺麗な推理を組み立てる。"},
    {"name": "レイ", "desc": "25歳男性。冷静な策士。表向きは普通に見せかけつつ、裏で盤面をコントロールしようとする。"},
    {"name": "ジン", "desc": "22歳男性。大胆な議論派。自分の意見をハッキリ主張し、議論の雰囲気をグイグイ引っ張る。"},
    {"name": "シェスタ", "desc": "19歳女性。社交的な議論派。場を和ませつつ、上手に他の人から情報を引き出すのが得意。"},
    {"name": "ルナ", "desc": "24歳女性。心理戦が得意な策士。あえてブラフを混ぜたり、相手の反応を面白がる。"}
]

ROLE_EMOJIS = {
    "人狼": "🐺", "市民": "👤", "占い師": "🔮", "怪盗": "🕵", 
    "狩人": "🎯", "てるてる": "☀", "魔女っ子": "🧙‍♀", "狂人": "🤫"
}

game = {
    "is_running": False, "mode": None, "phase": "idle", "channel": None,
    "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {},
    "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
    "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0},
    "pending_multi_host": None, "pending_multi_users": []
}

def reset_game_state():
    global game
    if game.get("discussion_task"): 
        game["discussion_task"].cancel()
    game.clear()
    game.update({
        "is_running": False, "mode": None, "phase": "idle", "channel": None,
        "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {},
        "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
        "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0},
        "pending_multi_host": None, "pending_multi_users": []
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

def find_mentioned_ai(text):
    for name, p in game["players"].items():
        if p["is_ai"] and name in text:
            return name, p
    return None, None

class RoleCountSelectView(discord.ui.View):
    def __init__(self, mode, human_users):
        super().__init__(timeout=300)
        self.mode = mode
        self.human_users = human_users
        self.roles = dict(game["selected_roles"])

    def create_embed(self):
        embed = discord.Embed(title="🎴 役職カスタム枚数設定", description="合計7枚にしてください。", color=discord.Color.blue())
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
            await i.response.send_message("⚠ 合計7枚にしてください。", ephemeral=True); return
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

    member_list_text = "👥 **【参加プレイヤー一覧】**\n" + "\n".join([f"・{n} ({'AI' if p['is_ai'] else '人間'})" for n, p in game["players"].items()])

    if mode == "watch":
        await channel.send(f"🍿 **観戦モード開始！** `!jinro next` で議論を1ターン進めてください。\n\n{member_list_text}")
    else:
        await channel.send(f"🌌 **ゲーム開始！** 夜の時間です。DMを確認して行動してください（完了したらサーバーで `!jinro next` または `!done` を入力してください）。\n\n{member_list_text}")
        
    await process_night_phase()

async def process_night_phase():
    wws = [n for n, p in game["players"].items() if p["role"] == "人狼"]
    
    for n, p in game["players"].items():
        if not p["is_ai"] and p["user_obj"]:
            msg = f"🌙 **役職: 『{p['role']}』**\n"
            if p["role"] == "人狼":
                msg += f"仲間: {', '.join([w for w in wws if w != n]) or 'なし（または墓場にいます）'}"
            elif p["role"] == "占い師":
                msg += "💬 占いには `!fortune プレイヤー名` または `!fortune 墓場`"
            elif p["role"] == "怪盗":
                msg += "💬 盗むには `!steal プレイヤー名`"
            elif p["role"] == "狩人":
                msg += "💬 道連れを指定するには `!hunt プレイヤー名`"
            elif p["role"] == "魔女っ子":
                msg += "💬 覗き見るには `!witch プレイヤー名`"
            else:
                msg += "今夜は静かに眠りましょう。"
            try: await p["user_obj"].send(msg)
            except: pass

    for n, p in game["players"].items():
        if p["is_ai"]:
            if p["role"] == "人狼":
                partners = [w for w in wws if w != n]
                p["ai_knows"] = f"仲間の人狼は 『{', '.join(partners) or 'なし'}』 です。"
            elif p["role"] == "占い師":
                t = random.choice([k for k in game["players"] if k != n])
                p["ai_knows"] = f"{t} は『{game['players'][t]['role']}』でした。"
            elif p["role"] == "怪盗":
                t = random.choice([k for k in game["players"] if k != n])
                my_old_role = game["players"][n]["role"]
                target_role = game["players"][t]["role"]
                
                game["players"][n]["role"] = target_role
                game["players"][t]["role"] = my_old_role
                
                is_wolf_faction = target_role in ["人狼", "狂人"]
                if is_wolf_faction:
                    fake_roles = ["市民", "占い師", "狩人", "魔女っ子"]
                    fake_role = random.choice([r for r in fake_roles if r != target_role])
                    p["ai_knows"] = f"{t} と役職を交換し、『{target_role}』になりました。ただし人狼陣営なので、議論では『{t} と交換して「{fake_role}」になった』と異なる役職を語る戦術をとってください。"
                else:
                    p["ai_knows"] = f"{t} と役職を交換し、『{target_role}』になりました。"
            elif p["role"] == "狩人":
                t = random.choice([k for k in game["players"] if k != n])
                game["hunter_targets"][n] = t
                p["ai_knows"] = f"{t} を道連れ指定しました。"
            elif p["role"] == "魔女っ子":
                t = random.choice([k for k in game["players"] if k != n])
                game["witch_targets"][n] = t
                p["ai_knows"] = f"{t} の役職は『{game['players'][t]['role']}』でした。"
            else:
                p["ai_knows"] = "平穏な夜の行動でした。"

async def generate_ai_discussion(user_input=""):
    if game["phase"] != "discussion": 
        return
    
    game["turn_count"] += 1
    ai_names = [n for n, p in game["players"].items() if p["is_ai"]]
    if not ai_names: 
        return

    if user_input:
        game["history"].append(f"人間発言: {user_input}")

    for speaker_name in ai_names:
        speaker_data = game["players"][speaker_name]
        current_role = speaker_data["role"]
        original_role = speaker_data.get("original_role", current_role)
        
        role_strategy_guide = ""
        if original_role == "怪盗":
            role_strategy_guide = (
                f"\n【🕵️ 怪盗としての戦術指示】\n"
                f"- あなたの夜の怪盗としての結果: {speaker_data.get('ai_knows', '')}\n"
                f"- **議論の中で、自分が誰と役職を交換して、何になったのかを必ず発言してください。**\n"
                f"- 指示に沿って、必要に応じて異なる役職を主張するブラフを活用してください。\n"
            )
        elif original_role == "てるてる":
            role_strategy_guide = (
                f"\n【☀ てるてる坊主としての戦術指示】\n"
                f"- **自分が選択される（追放される）ために、目立つ動きをしてください。**\n"
                f"- 具体的には、**「自分は狩人だ」と宣言する**、あるいは独特な主張や予想を語るなどして、他の参加者から関心や票を集めるような立ち回りをしてください。\n"
            )
        elif current_role == "人狼":
            role_strategy_guide = (
                f"\n【🐺 人狼陣営としての戦術指示】\n"
                f"- あなたの夜の仲間情報: {speaker_data.get('ai_knows', '')}\n"
                f"- **正体を隠した上で、村人陣営を混乱させるためにカモフラージュ戦術や架空の調査結果を活用してください。**\n"
                f"- 必要に応じて、自分が「占い師」などの役職であると主張（CO）し、実際とは異なる調査結果を語って議論を誘導しても構いません。\n"
                f"- 相方の情報をあえて別の視点から語るなど、生き残りと駆け引きを優先してください。\n"
            )
        elif current_role == "狂人":
            role_strategy_guide = (
                f"\n【🤫 狂人陣営としての戦術指示】\n"
                f"- あなたの夜の行動・知っている情報: {speaker_data.get('ai_knows', '')}\n"
                f"- **自分が狂人であることは表に出さずに行動してください。**\n"
                f"- 村人陣営を撹乱するために、積極的に「占い師」などの役職を名乗って独自の情報を主張したり、議論に変化を与えてください。\n"
            )
        else:
            role_strategy_guide = (
                f"\n【👤 村人陣営としての戦術指示】\n"
                f"- あなたの夜の行動・知っている情報: {speaker_data.get('ai_knows','')}\n"
                f"- **あなたは村人側の参加者です。自分の役職や夜の行動結果をしっかり伝えて勝利を目指してください。**\n"
            )

        # ターンが進むにつれて（特に後半戦）、誰をマークするかを強く要求する共通指示
        focus_push = ""
        if game["turn_count"] >= 3:
            focus_push = (
                f"\n【🚨 終盤の重要指示】\n"
                f"- 現在は後半戦（ターン {game['turn_count']} / 5）です。\n"
                f"- 投票先を決めるにあたり、**「誰を一番マークしているか（不審に思っているか）」**や**「誰なら信頼できる・村人だと思うか」**を、他の参加者の具体的な名前を出してハッキリ主張してください。\n"
            )

        prompt = (
            f"ワンナイト人狼の議論タイム（全5ターンのうち、現在は【ターン {game['turn_count']} / 5】）。\n"
            f"あなたは『{speaker_name}』です（キャラクター設定: {speaker_data['desc']}）。\n"
            f"{role_strategy_guide}"
            f"{focus_push}\n\n"
            f"【ルール・方針】\n"
            f"- 自分の本当の正体や役職名をそのままチャットで告白するのは禁止です。\n"
            f"- 他のプレイヤーのこれまでの発言に対する意見を、現実のチャットのような適度な長さで発言してください。\n\n"
            f"【これまでの議論ログ】\n" + "\n".join(game["history"][-12:]) + f"\n\n"
            f"【最新の状況】\n"
            f"{user_input if speaker_name == ai_names[0] else '（他のメンバーに続いてあなたの番です）'}"
        )
        
        try:
            async with game["channel"].typing():
                reply = await call_llm(prompt)
                if reply:
                    game["history"].append(f"{speaker_name}: {reply}")
                    await send_split_message(game["channel"], f"🗣️ **【ターン {game['turn_count']} / 5】 {speaker_name}**: {reply}")
                    await asyncio.sleep(1.5)
        except Exception as e:
            print(f"[議論エラー ({speaker_name})]: {e}")

    if game["turn_count"] >= 5:
        await game["channel"].send("\n🚨 **5ターン終了！投票タイムへ移行します。**")
        await start_voting_phase()
    else:
        await game["channel"].send(f"👇 **【ターン {game['turn_count']} 終了】** 次のターンに進むには `!jinro next` と入力してください。")

async def handle_jinro_command(message, actual_text, author_name):
    text_lower = actual_text.strip().lower()
    
    if text_lower in ["clear", "reset", "stop", "abort", "終了", "リセット"]:
        reset_game_state()
        await message.channel.send("🧹 **ゲームを強制リセットしました。** 新しくゲームを始めるにはセットアップを行ってください。")
        return

    remaining_text = actual_text
    for cmd in ["next", "n", "次"]:
        if text_lower == cmd or text_lower.startswith(cmd + " ") or text_lower.startswith(cmd + "　"):
            remaining_text = actual_text[len(cmd):].strip()
            break

    if game["phase"] == "night":
        if text_lower in ["next", "n", "次", "done"]:
            game["phase"] = "discussion"
            if game["mode"] == "watch":
                await game["channel"].send("☀ **朝になりました！ `!jinro next` で議論を1ターン進めてください。**")
            elif game["mode"] == "multi":
                await game["channel"].send("☀️ **朝になりました！議論タイム開始 (`!jinro 発言` / 投票はDMで `!vote プレイヤー名` または `!vote 平和`)**")
                game["discussion_task"] = asyncio.create_task(start_5min_timer())
            else:
                await game["channel"].send("☀ **朝になりました！最初のターンを開始するには `!jinro next` と入力してください。**")
            return
        else:
            await message.channel.send("🌙 現在は夜のフェーズです。DMで夜の行動を終えたら、`!jinro next` と入力して朝へ進めてください。（※やり直す場合は `!jinro clear`）")
            return

    if game["mode"] == "solo":
        await generate_ai_discussion(user_input=f"{author_name}: {remaining_text}" if remaining_text else "")
    elif game["mode"] == "watch":
        await generate_ai_discussion(user_input=f"{author_name}: {remaining_text}" if remaining_text else "")
    elif game["mode"] == "multi":
        ai_name, target_ai = find_mentioned_ai(actual_text)
        if ai_name and target_ai:
            prompt = (
                f"ワンナイト人狼の議論中。あなたは『{ai_name}』です（キャラクター設定: {target_ai['desc']}）。\n"
                f"プレイヤー({author_name})からの発言: 「{actual_text}」\n"
                f"この発言に対して、あなたのキャラクターになりきって短く返答してください。"
            )
            try:
                async with message.channel.typing():
                    reply = await call_llm(prompt)
                    if reply:
                        game["history"].append(f"{author_name}: {actual_text}")
                        game["history"].append(f"{ai_name}の返答: {reply}")
                        await send_split_message(message.channel, f"🗣 **{ai_name}**: {reply}")
            except Exception as e:
                print(f"[AI個別返答エラー]: {e}")
        else:
            game["history"].append(f"{author_name}: {actual_text}")
            await message.add_reaction("👍")
async def start_voting_phase():
    game["phase"] = "voting"
    await game["channel"].send("🗳️ **投票タイム**（AIたちはそれぞれの思惑をもとに投票先を考えています...）")
    
    discussion_log = "\n".join(game["history"]) if game["history"] else "（議論はあまり行われませんでした）"

    for n, p in game["players"].items():
        if not p["is_ai"]: continue
        
        role_hint = ""
        if p["role"] == "人狼":
            partners = [w for w, wp in game["players"].items() if wp["role"] == "人狼" and w != n]
            partner_str = f"（あなたの仲間の人狼: {', '.join(partners) if partners else 'なし'}）"
            valid_targets = [k for k in game["players"].keys() if k != n and k not in partners] + ["平和"]
            role_hint = (
                f"あなたは人狼です{partner_str}。\n"
                f"🚨 **絶対のルール**: 仲間の人狼（{', '.join(partners) if partners else 'なし'}）には**絶対に投票してはいけません**。\n"
                f"仲間以外のプレイヤー、または「平和」の中から、一番注目すべきだと思うものを選んでください。"
            )
        else:
            valid_targets = [k for k in game["players"].keys() if k != n] + ["平和"]
            if p["role"] == "てるてる":
                role_hint = "あなたはてるてる坊主です。自分が選択されるために、議論で注目を集めたプレイヤーの方向へ票を誘導したいところです。"
            else:
                role_hint = "あなたは村人陣営です。議論ログをよく読んで、最も重要だと思う人に投票してください。"

        prompt = (
            f"ワンナイト人狼の投票フェーズです。あなたは『{n}』です（キャラクター設定: {p['desc']}）。\n\n"
            f"【これまでの議論ログ】\n{discussion_log}\n\n"
            f"【あなたの立場と指針】\n{role_hint}\n\n"
            f"【投票可能な候補】\n{', '.join(valid_targets)}\n\n"
            f"周りの意見に流されず、上記の候補の中から投票先を選んでください。\n"
            f"【回答ルール】投票したいプレイヤーの名前、または「平和」のいずれか**一単語のみ**を答えてください。"
        )
        
        try:
            reply = await call_llm(prompt)
            if reply:
                cleaned_reply = reply.strip().replace("「", "").replace("」", "").replace("。", "")
                
                voted_target = None
                if "平和" in cleaned_reply:
                    voted_target = "平和"
                else:
                    for k in game["players"].keys():
                        if k in cleaned_reply and k != n:
                            if p["role"] == "人狼":
                                partners = [w for w, wp in game["players"].items() if wp["role"] == "人狼" and w != n]
                                if k in partners:
                                    continue
                            voted_target = k
                            break
                
                if not voted_target or voted_target == n or voted_target not in valid_targets:
                    voted_target = random.choice(valid_targets)
                
                game["votes"][n] = voted_target
            else:
                game["votes"][n] = random.choice(valid_targets)
        except Exception as e:
            print(f"[AI投票エラー ({n})]: {e}")
            game["votes"][n] = random.choice(valid_targets)

    human_players = [n for n, p in game["players"].items() if not p["is_ai"]]
    if len(human_players) == 0:
        await asyncio.sleep(1)
        await Tally_and_finish()
    else:
        await game["channel"].send("🗳 AIの投票が完了しました！人間プレイヤーは `!vote プレイヤー名` または `!vote 平和` で投票してください。")

async def Tally_and_finish():
    game["phase"] = "ended"
    if game.get("discussion_task"): 
        game["discussion_task"].cancel()

    counts = {}
    peace_count = 0
    for v, t in game["votes"].items():
        if t == "平和": peace_count += 1
        else: counts[t] = counts.get(t, 0) + 1

    res = "⚖ **集計結果**\n"
    max_v = max(counts.values()) if counts else 0
    lynched = [k for k, c in counts.items() if c == max_v] if max_v > 0 else []

    for v, t in game["votes"].items():
        res += f"・{v} ➔ {t}\n"

    if game.get("channel"):
        await game["channel"].send(res)

    win_reason = ""
    if len(lynched) == 1 and game["players"][lynched[0]]["role"] == "てるてる":
        win_reason = f"☀ てるてる({lynched[0]})が選ばれたため、**てるてる陣営の勝利**です！"
    elif peace_count > (len(game["votes"]) / 2):
        wws_alive = [n for n, p in game["players"].items() if p["role"] == "人狼"]
        win_reason = "🕊️ 平和が選ばれ、人狼がいなかったため**村人陣営の勝利**です！" if not wws_alive else "🐺 平和が選ばれましたが人狼が生き残っていたため**人狼陣営の勝利**です！"
    elif len(lynched) == 1:
        target = lynched[0]
        role = game["players"][target]["role"]
        win_reason = f"🎉 人狼である **{target}** が選ばれたため、**村人陣営の勝利**です！" if role == "人狼" else f"😢 選ばれた **{target}** は人狼ではありませんでした。**人狼陣営の勝利**です！"
    else:
        win_reason = "⚖️ 同票のため誰も選ばれず、人狼陣営の勝利です！"

    roles_text = "🎴 **【役職公開】**\n" + "\n".join([f"・{n}: 当初({p['original_role']}) ➔ 最終({p['role']})" for n, p in game["players"].items()])
    center_text = f"・中央の余りカード: {', '.join(game['center_cards'])}"
    
    if game.get("channel"):
        await game["channel"].send(f"{win_reason}\n\n{roles_text}\n{center_text}")

        # === 安全な表現に調整した感想戦 ===
        await asyncio.sleep(2)
        await game["channel"].send("💬 **【感想戦】** 実際の議論や結果を振り返って、AIたちがアフタートークを始めます...")
        
        discussion_log = "\n".join(game["history"]) if game["history"] else "（議論はあまり行われませんでした）"
        ai_names = [n for n, p in game["players"].items() if p["is_ai"]]
        
        for ai_name in ai_names:
            p_data = game["players"][ai_name]
            prompt = (
                f"ワンナイト人狼のゲームが終了し、勝敗と本当の役職が公開されました。\n"
                f"あなたは『{ai_name}』（キャラクター設定: {p_data['desc']}）でした。\n"
                f"- あなたの役職: 当初({p_data['original_role']}) ➔ 最終({p_data['role']})\n\n"
                f"【これまでの実際の議論ログ】\n{discussion_log}\n\n"
                f"上記の**議論のやり取りや他の人の発言、そして今回の役職公開の結果を踏まえて**、\n"
                f"「誰のどの発言に惑わされたか」「誰を信じて推理したか、あるいはうまく正体を隠して立ち回れたか」などを、\n"
                f"実際の議論の具体的な内容に触れながら、キャラクターになりきって短く1〜2文で感想を語ってください。"
            )
            try:
                reply = await call_llm(prompt)
                if reply:
                    await send_split_message(game["channel"], f"🗣️ **{ai_name}の感想**: {reply}")
                    await asyncio.sleep(1.2)
            except Exception as e:
                print(f"[感想戦エラー ({ai_name})]: {e}")

    reset_game_state()
