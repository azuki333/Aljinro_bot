import discord
import urllib.request
import urllib.error
import json
import asyncio
import os
import random
import traceback

# --- Discord Client 設定 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# --- 環境変数の取得 ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# --- AIキャラクター設定（5人） ---
AI_CHARACTERS = [
    {"name": "レン", "desc": "20代男性。冷静沈着で論理적。矛盾や怪しい発言を見逃さず詰めるタイプ。"},
    {"name": "ユイ", "desc": "17歳女子高生。直感重視で天然だが直感が当たる。感情的で畳みかける。"},
    {"name": "Gemini-A", "desc": "確率とログ分析重視。長文で客観的なロジックを展開する分析派。"},
    {"name": "Gemini-B", "desc": "心理戦が得意。発言の矛盾を突き、他人に疑いを向けるブラフを多用する。"},
    {"name": "タクミ", "desc": "30代ベテラン。議論を誘導したり、盤面を乱して様子を見る戦略派。"}
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
    "phase": "idle",       # "night", "discussion", "voting", "ended"
    "channel": None,
    "players": {},
    "center_cards": [],
    "votes": {},
    "hunter_targets": {},  # 狩人が道連れに指定したターゲット
    "turn_count": 0,
    "discussion_task": None,
    "history": [],
    # デフォルトの役職枚数（同じ役職を複数持てる辞書形式）
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

# --- Discordへの自動分割送信処理 ---
async def send_split_message(channel, content):
    if not content or not channel:
        return
    chunk_size = 1900
    for i in range(0, len(content), chunk_size):
        try:
            await channel.send(content[i:i+chunk_size])
        except Exception as e:
            print(f"[送信エラー]: {e}")

# --- API呼出 ---
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
                        return (text if not debug else f"【Gemini応答成功】\n{text}")
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
                    return (data["choices"][0]["message"]["content"] if not debug else f"【OpenAI応答成功】\n{data['choices'][0]['message']['content']}")
        except Exception as e:
            errors.append(f"OpenAI Error: {e}")

    if debug:
        return "❌ 両方のAPI呼出に失敗しました。\n" + "\n".join(errors)
    return None

async def call_llm(prompt_content, debug=False):
    try:
        return await asyncio.to_thread(_sync_call_llm, prompt_content, debug)
    except Exception as e:
        print(f"[LLM Task Error]: {e}")
        return None

@client.event
async def on_ready():
    print(f'🤖 【人狼＆雑談 Bot】完全版 起動完了: {client.user.name}')

async def start_5min_timer():
    try:
        await asyncio.sleep(300)
        if game["is_running"] and game["phase"] == "discussion":
            await game["channel"].send("🚨 **【5分経過・議論終了！】** タイムアップです！これより投票タイムに移ります。")
            await start_voting_phase()
    except asyncio.CancelledError:
        pass

# --- 役職カスタム増減用ビュー（同じ役職を複数追加できるボタン式） ---
class RoleCountSelectView(discord.ui.View):
    def __init__(self, mode, human_users):
        super().__init__(timeout=300)
        self.mode = mode
        self.human_users = human_users
        # 現在の設定をコピーして保持
        self.roles = dict(game["selected_roles"])

    def create_embed(self):
        embed = discord.Embed(
            title="🎴 役職カスタム枚数設定パネル",
            description="ボタンを押して、使いたい役職の枚数を自由に増減させてください。（同じ役職を何枚でも入れられます！）\n※5人プレイの場合、**合計7枚**（プレイヤー5枚 ＋ 中央墓場2枚）になるように調整してください。",
            color=discord.Color.blue()
        )
        
        total = 0
        for role, count in self.roles.items():
            emoji = ROLE_EMOJIS.get(role, "")
            embed.add_field(name=f"{emoji} {role}", value=f"**{count}** 枚", inline=True)
            total += count
            
        embed.set_footer(text=f"現在の合計カード枚数: {total} 枚 (推奨: 7枚)")
        return embed

    # --- 人狼 ---
    @discord.ui.button(label="🐺 人狼+", style=discord.ButtonStyle.danger, row=0)
    async def add_ww(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["人狼"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="人狼-", style=discord.ButtonStyle.secondary, row=0)
    async def sub_ww(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["人狼"] > 0:
            self.roles["人狼"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- 市民 ---
    @discord.ui.button(label="👤 市民+", style=discord.ButtonStyle.primary, row=1)
    async def add_cit(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["市民"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="市民-", style=discord.ButtonStyle.secondary, row=1)
    async def sub_cit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["市民"] > 0:
            self.roles["市民"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- 占い師 ---
    @discord.ui.button(label="🔮 占い+", style=discord.ButtonStyle.success, row=2)
    async def add_see(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["占い師"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="占い-", style=discord.ButtonStyle.secondary, row=2)
    async def sub_see(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["占い師"] > 0:
            self.roles["占い師"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- 怪盗 ---
    @discord.ui.button(label="🕵️ 怪盗+", style=discord.ButtonStyle.success, row=2)
    async def add_thf(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["怪盗"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="怪盗-", style=discord.ButtonStyle.secondary, row=2)
    async def sub_thf(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["怪盗"] > 0:
            self.roles["怪盗"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- 狩人 ---
    @discord.ui.button(label="🎯 狩人+", style=discord.ButtonStyle.success, row=3)
    async def add_hnt(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["狩人"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="狩人-", style=discord.ButtonStyle.secondary, row=3)
    async def sub_hnt(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["狩人"] > 0:
            self.roles["狩人"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- てるてる ---
    @discord.ui.button(label="☀️ てる+", style=discord.ButtonStyle.success, row=3)
    async def add_teru(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.roles["てるてる"] += 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="てる-", style=discord.ButtonStyle.secondary, row=3)
    async def sub_teru(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.roles["てるてる"] > 0:
            self.roles["てるてる"] -= 1
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    # --- 決定ボタン ---
    @discord.ui.button(label="🚀 この構成でゲーム開始！", style=discord.ButtonStyle.blurple, row=4)
    async def confirm_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        total = sum(self.roles.values())
        if total != 7:
            await interaction.response.send_message(f"⚠️ 5人プレイでは合計 **7枚** 必要です（現在 {total} 枚）。枚数を見直してください。", ephemeral=True)
            return
        
        game["selected_roles"] = dict(self.roles)
        await interaction.response.send_message("✨ 役職の構成が確定しました！ゲームをセットアップします…", ephemeral=True)
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

        needed_ai_count = 5 - len(all_participants)
        if needed_ai_count > 0:
            selected_ais = random.sample(AI_CHARACTERS, needed_ai_count)
            for ai in selected_ais:
                all_participants.append({"name": ai["name"], "is_ai": True, "user_obj": None, "desc": ai["desc"]})

    # 辞書からリスト（プール）を組み立て
    pool = []
    for role, count in game["selected_roles"].items():
        for _ in range(count):
            pool.append(role)

    random.shuffle(pool)
    game["center_cards"] = [pool.pop(), pool.pop()]

    for p in all_participants:
        assigned_role = pool.pop()
        game["players"][p["name"]] = {
            "is_ai": p["is_ai"],
            "user_obj": p["user_obj"],
            "role": assigned_role,
            "original_role": assigned_role,
            "desc": p.get("desc", "")
        }

    if mode == "watch":
        await channel.send(
            f"🍿 **【ワンナイト人狼 - 観戦モード】**\n"
            f"参戦AI: **{', '.join(game['players'].keys())}**\n"
            f"準備完了！ `!jinro next` でターン1の議論を開始します。"
        )
    else:
        ai_names = [n for n, p in game["players"].items() if p["is_ai"]]
        ai_status_msg = f"（AIプレイヤー: {', '.join(ai_names)} が参戦）" if ai_names else "（👥 完全人間での対戦）"
        await channel.send(
            f"🌌 **【ワンナイト人狼】ゲームを開始します！**\n"
            f"参加者: **{', '.join(game['players'].keys())}** {ai_status_msg}\n"
            f"現在『夜の時間』です。人間プレイヤーに個別DMで役職を通知しています…"
        )

    await process_night_phase()

async def process_night_phase():
    werewolves = [name for name, p in game["players"].items() if p["role"] == "人狼"]

    for name, p in game["players"].items():
        if not p["is_ai"] and p["user_obj"]:
            msg = f"🌙 **【あなたの役職】: 『{p['role']}』**\n"
            if p["role"] == "人狼":
                other_wolves = [w for w in werewolves if w != name]
                msg += f"仲間: **【{', '.join(other_wolves)}】**" if other_wolves else "（仲間なし）"
            elif p["role"] == "占い師":
                msg += "💬 DMで `!fortune プレイヤー名` または `!fortune 墓場` と送信してください。"
            elif p["role"] == "怪盗":
                msg += "💬 DMで `!steal プレイヤー名` と送信してください。"
            elif p["role"] == "狩人":
                msg += "💬 DMで `!hunt プレイヤー名` と送信してください。"
            elif p["role"] == "魔女っ子":
                msg += "💬 DMで `!witch プレイヤー名` と送信してください。"
            elif p["role"] == "狂人":
                msg += "💬 あなたは狂人です。人狼陣営を勝利に導いてください。"
            elif p["role"] == "てるてる":
                msg += "💬 あなたはてるてる坊主です。昼の投票で処刑されれば単独勝利です！"
            
            try:
                await p["user_obj"].send(msg)
            except Exception as e:
                print(f"[DM送信失敗]: {e}")
                await game["channel"].send(f"⚠️ {name} さんへのDM送信に失敗しました。")

    for name, p in game["players"].items():
        if p["is_ai"]:
            if p["role"] == "占い師":
                target = random.choice([n for n in game["players"].keys() if n != name])
                p["ai_knows"] = f"{target} さんの役職は『{game['players'][target]['role']}』でした。"
            elif p["role"] == "怪盗":
                target = random.choice([n for n in game["players"].keys() if n != name])
                game["players"][name]["role"], game["players"][target]["role"] = game["players"][target]["role"], game["players"][name]["role"]
                p["ai_knows"] = f"{target} さんと役職を交換しました。"
            elif p["role"] == "狩人":
                target = random.choice([n for n in game["players"].keys() if n != name])
                game["hunter_targets"][name] = target
                p["ai_knows"] = f"{target} さんを道連れ候補に指定しました。"
            else:
                p["ai_knows"] = "平穏な夜を過ごしました。"

    game["phase"] = "discussion"

    if game["mode"] != "watch":
        await game["channel"].send("☀️ **朝になりました！これより議論タイムを開始します。**")
        if game["mode"] == "multi":
            await game["channel"].send("⏱️ **【制限時間: 5分】** `!jinro 発言内容` でAIに割り込めます。")
            game["discussion_task"] = asyncio.create_task(start_5min_timer())
        else:
            await game["channel"].send("💬 **【全5ターン制】** `!jinro 発言内容` で発言してください。")
            await generate_ai_discussion("（議論を開始してください。）")

async def generate_ai_discussion(user_input="", is_watch=False):
    if game["phase"] != "discussion":
        return

    game["turn_count"] += 1
    ai_players_info = []
    for name, p in game["players"].items():
        if p["is_ai"]:
            knows = p.get("ai_knows", "特別な夜の情報はありません。")
            ai_players_info.append(
                f"- {name} ({p['desc']}): 元『{p['original_role']}』, 現在『{p['role']}』. 夜の知見: {knows}"
            )

    recent_history = game["history"][-10:] if len(game["history"]) >= 10 else game["history"]

    prompt = f"""あなたは「ワンナイト人狼」の高度なAIプレイヤーたちを演じるGMです。

【現在のターン】: {game['turn_count']} / 5 ターン
【AIプレイヤー情報】
{chr(10).join(ai_players_info)}
【これまでの会話ログ】
{chr(10).join(recent_history)}

【出力ルール】
・議論やCOのやり取り（発言のみ）を出力してください。
・ユーザーの入力文をそのまま復唱しないでください。"""

    try:
        async with game["channel"].typing():
            ai_reply = await call_llm(prompt)
            if ai_reply:
                if user_input:
                    game["history"].append(f"人間発言: {user_input}")
                game["history"].append(ai_reply)
                header = f"🗣️ **【ターン {game['turn_count']} / 5】**\n" if is_watch else ""
                await send_split_message(game["channel"], header + ai_reply)
            else:
                await game["channel"].send("⚠️ AI応答が混雑のため取得できませんでした。")
    except Exception as e:
        print(f"[議論生成エラー]: {e}")

    if game["turn_count"] >= 5:
        await game["channel"].send("\n🚨 **【5ターン終了】** これより投票タイムに移ります！")
        await start_voting_phase()

async def start_voting_phase():
    game["phase"] = "voting"
    await game["channel"].send("🗳️ **【投票タイム】** 誰を処刑するか投票中...")

    for name, p in game["players"].items():
        if p["is_ai"]:
            candidates = [n for n in game["players"].keys() if n != name]
            game["votes"][name] = random.choice(candidates)

    humans = [n for n, p in game["players"].items() if not p["is_ai"]]
    if len(humans) == 0:
        await asyncio.sleep(2)
        await Tally_and_finish()

# --- 勝敗集計 ---
async def Tally_and_finish():
    game["phase"] = "ended"
    game["is_running"] = False

    if game["discussion_task"]:
        game["discussion_task"].cancel()

    vote_counts = {}
    for voter, target in game["votes"].items():
        vote_counts[target] = vote_counts.get(target, 0) + 1

    max_votes = max(vote_counts.values()) if vote_counts else 0
    executed = [n for n, c in vote_counts.items() if c == max_votes]

    res_msg = "⚖️ **【集計結果】**\n"
    for voter, target in game["votes"].items():
        res_msg += f"・{voter} ➡️ {target}\n"

    res_msg += "\n🩸 **【処刑結果】**\n"
    executed_player = None
    dragged_player = None

    if len(executed) == 1:
        executed_player = executed[0]
        res_msg += f"最多得票により、**【{executed_player}】** が処刑されました！\n"

        if game["players"][executed_player]["role"] == "狩人" and executed_player in game["hunter_targets"]:
            dragged_player = game["hunter_targets"][executed_player]
            res_msg += f"🎯 **【狩人の道連れ発動！】** 処刑された狩人（{executed_player}）は、道連れとして **【{dragged_player}】** を巻き添えにしました！\n"
    else:
        res_msg += f"票が割れたため、**【平和村（処刑なし）】** となりました！\n"

    werewolves = [n for n, p in game["players"].items() if p["role"] == "人狼"]
    
    res_msg += "\n🎉 **【勝敗発表】**\n"
    
    if executed_player and game["players"][executed_player]["role"] == "てるてる":
        res_msg += "☀️ **【てるてる坊主】の単独勝利！**（見事処刑されました！）\n"
    elif dragged_player and game["players"][dragged_player]["role"] == "てるてる":
        res_msg += "☀️ **【てるてる坊主】の単独勝利！**（道連れで処刑されました！）\n"
    else:
        hunter_win = False
        hunter_lose = False
        if executed_player and game["players"][executed_player]["role"] == "狩人":
            if dragged_player:
                dragged_role = game["players"][dragged_player]["role"]
                if dragged_role == "人狼":
                    hunter_win = True
                else:
                    hunter_lose = True

        if hunter_win:
            res_msg += "🏆 **市民陣営の勝利！**（狩人が人狼を道連れにしました！）\n"
        elif hunter_lose:
            res_msg += "🐺 **人狼陣営の勝利！**（狩人が村人を道連れにしてしまいました…）\n"
        elif executed_player and game["players"][executed_player]["role"] == "人狼":
            res_msg += "🏆 **市民陣営の勝利！**（人狼を処刑できました！）\n"
        elif not executed_player and len(werewolves) == 0:
            res_msg += "🏆 **市民陣営の勝利！**（平和村達成！）\n"
        else:
            res_msg += "🐺 **人狼陣営（＋狂人）の勝利！**\n"

    res_msg += "\n📜 **【正解（最終役職）】**\n"
    for n, p in game["players"].items():
        orig = f" (元: {p['original_role']})" if p['original_role'] != p['role'] else ""
        res_msg += f"・{n}: 『{p['role']}』{orig}\n"
    res_msg += f"・墓場: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』\n"

    await send_split_message(game["channel"], res_msg)

# --- メッセージ受信イベント ---
@client.event
async def on_message(message):
    global game

    if message.author.bot:
        return

    content = message.content.strip()

    try:
        if content == '!help':
            help_text = (
                "🤖 **【Aljinro_bot 完全版コマンド一覧】**\n\n"
                "**💬 雑談・テスト**\n"
                "・`!chat <メッセージ>` : AIキ
