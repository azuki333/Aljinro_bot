import discord
import urllib.request
import urllib.error
import json
import asyncio
import os
import random

# --- Discord Client 設定 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# --- 環境変数の取得 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# --- AIキャラクター設定（5人） ---
AI_CHARACTERS = [
    {"name": "レン", "desc": "20代男性。冷静沈着で論理的。理由を深掘りして詰めるタイプ。"},
    {"name": "ユイ", "desc": "17歳女子高生。直感重視で天然だが、直感で真実を突く。言動が感情的。"},
    {"name": "Gemini-A", "desc": "確率とログ分析重視。長文で客観的なロジックを展開する。"},
    {"name": "Gemini-B", "desc": "人間の心理や発言の矛盾を鋭く突き、誘導やブラフも使う。"},
    {"name": "タクミ", "desc": "30代ベテラン。他人に振って様子を見たり、盤面を混乱させたりするのが得意。"}
]

# --- 役職定義 (5人プレイ: 計7枚) ---
ROLES_POOL = ["人狼", "人狼", "占い師", "怪盗", "市民", "市民", "市民"]

# --- ゲーム状態管理 ---
game = {
    "is_running": False,
    "mode": None,          # "solo", "multi", "watch"
    "phase": "idle",       # "night", "discussion", "voting", "ended"
    "channel": None,
    "players": {},
    "center_cards": [],    # 墓場のカード2枚
    "votes": {},           # voter -> target
    "turn_count": 0,
    "discussion_task": None,
    "history": []          # 発言ログ
}

# --- Discordへの自動分割送信処理 ---
async def send_split_message(channel, content):
    if not content:
        return
    chunk_size = 1900
    for i in range(0, len(content), chunk_size):
        await channel.send(content[i:i+chunk_size])

# --- 同期型のAPI呼び出し処理 ---
def _sync_call_llm(prompt_content, debug=False):
    errors = []

    # 1. Gemini API
    if GEMINI_API_KEY:
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt_content}]}]}
            req = urllib.request.Request(gemini_url, data=json.dumps(payload).encode('utf-8'), headers=HTTP_HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=10.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "candidates" in data and len(data["candidates"]) > 0:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    if len(text) > 5:
                        return (text if not debug else f"【Gemini応答成功】\n{text}")
        except Exception as e:
            err_msg = f"Gemini Error: {e}"
            print(err_msg)
            errors.append(err_msg)

    # 2. ChatGPT (OpenAI API)
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
            with urllib.request.urlopen(req, timeout=10.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "choices" in data and len(data["choices"]) > 0:
                    text = data["choices"][0]["message"]["content"]
                    return (text if not debug else f"【ChatGPT(OpenAI)応答成功】\n{text}")
        except Exception as e:
            err_msg = f"OpenAI Error: {e}"
            print(err_msg)
            errors.append(err_msg)

    if debug:
        return "❌ 両方のAPI呼出に失敗しました。\n" + "\n".join(errors)

    return None

# --- 非同期で呼び出すメイン関数 ---
async def call_llm(prompt_content, debug=False):
    return await asyncio.to_thread(_sync_call_llm, prompt_content, debug)

@client.event
async def on_ready():
    print(f'🤖 【人狼＆雑談 Bot】起動成功！ ({client.user.name})')

# --- 5分タイマー処理 ---
async def start_5min_timer():
    await asyncio.sleep(300)
    if game["is_running"] and game["phase"] == "discussion":
        await game["channel"].send("🚨 **【5分経過・議論終了！】** タイムアップです！これより投票タイムに移ります。")
        await start_voting_phase()

# --- ゲームセットアップ ---
async def setup_game(channel, mode, human_users=None):
    global game
    game["is_running"] = True
    game["mode"] = mode
    game["phase"] = "night"
    game["channel"] = channel
    game["players"] = {}
    game["votes"] = {}
    game["turn_count"] = 0
    game["history"] = []

    human_users = human_users or []
    all_participants = []

    # 観戦モード(watch)の場合はAI5人のみで構成
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

    shuffled_roles = random.sample(ROLES_POOL, len(ROLES_POOL))
    game["center_cards"] = [shuffled_roles.pop(), shuffled_roles.pop()]

    for p in all_participants:
        assigned_role = shuffled_roles.pop()
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
            f"AI5人のみで全自動対戦を行います！見守ってください。"
        )
    else:
        ai_names = [n for n, p in game["players"].items() if p["is_ai"]]
        ai_status_msg = f"（AIプレイヤー: {', '.join(ai_names)} が参戦）" if ai_names else "（👥 完全人間5人での対戦）"
        await channel.send(
            f"🌌 **【ワンナイト人狼】ゲームを開始します！**\n"
            f"参加者: **{', '.join(game['players'].keys())}** {ai_status_msg}\n"
            f"現在『夜の時間』です。人間プレイヤーに個別DMで役職を通知しています…"
        )

    await process_night_phase()

# --- 夜の処理 ---
async def process_night_phase():
    werewolves = [name for name, p in game["players"].items() if p["role"] == "人狼"]

    # 人間への通知
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
            
            try:
                await p["user_obj"].send(msg)
            except Exception:
                await game["channel"].send(f"⚠️ {name} さんへのDM送信に失敗しました。")

    # AIの夜行動
    for name, p in game["players"].items():
        if p["is_ai"]:
            if p["role"] == "占い師":
                if random.random() < 0.5:
                    p["ai_knows"] = f"墓場のカードは『{game['center_cards'][0]}』と『{game['center_cards'][1]}』でした。"
                else:
                    target = random.choice([n for n in game["players"].keys() if n != name])
                    p["ai_knows"] = f"{target} さんの役職は『{game['players'][target]['role']}』でした。"
            elif p["role"] == "怪盗":
                if random.random() < 0.7:
                    target = random.choice([n for n in game["players"].keys() if n != name])
                    game["players"][name]["role"], game["players"][target]["role"] = game["players"][target]["role"], game["players"][name]["role"]
                    p["ai_knows"] = f"{target} さんと役職を交換しました。現在の役職は『{game['players'][name]['role']}』です。"
                else:
                    p["ai_knows"] = "役職の交換を行いませんでした。"

    await game["channel"].send("☀️ **朝になりました！これより議論タイムを開始します。**")
    game["phase"] = "discussion"

    if game["mode"] == "watch":
        # 観戦モードは全自動で1〜5ターンを連続実行
        await run_watch_mode_discussion()
    elif game["mode"] == "multi":
        await game["channel"].send("⏱️ **【制限時間: 5分】** `!jinro 発言内容` でAIに割り込めます。")
        game["discussion_task"] = asyncio.create_task(start_5min_timer())
    else:
        await game["channel"].send("💬 **【全5ターン制】** `!jinro 発言内容` で発言してください。")
        await generate_ai_discussion("（議論を開始してください。）")

# --- 観戦モード専用の全自動議論ループ ---
async def run_watch_mode_discussion():
    for turn in range(1, 6):
        if not game["is_running"]:
            return
        await game["channel"].send(f"\n🗣️ **【ターン {turn} / 5】**")
        await generate_ai_discussion(is_watch=True)
        await asyncio.sleep(3) # 読みやすさのためのウエイト

    await game["channel"].send("\n🚨 **【5ターン終了】** 観戦モードの議論が完了しました。これより投票に移ります！")
    await start_voting_phase()

# --- AI議論生成 ---
async def generate_ai_discussion(user_input="", is_watch=False):
    if game["phase"] != "discussion":
        return

    game["turn_count"] += 1
    
    ai_players_info = []
    for name, p in game["players"].items():
        if p["is_ai"]:
            knows = p.get("ai_knows", "特別な夜の情報はありません。")
            ai_players_info.append(f"- {name} ({p['desc']}): 元の役職『{p['original_role']}』, 現在の役職『{p['role']}』. 夜の知識: {knows}")

    recent_history = game["history"][-10:] if len(game["history"]) >= 10 else game["history"]

    prompt = f"""あなたは「ワンナイト人狼」のAIプレイヤーたちを演じる高度なGMです。
以下の状況を踏まえて、リアルで白熱する議論の会話を作成してください。

【現在のターン】: {game['turn_count']} / 5 ターン

【AIプレイヤー情報】
{chr(10).join(ai_players_info)}

【直近の会話ログ】
{chr(10).join(recent_history)}

【重要ルール】
・ユーザーの入力をそのまま文章中に復唱しないでください。
・各AIキャラクター（{', '.join([n for n, p in game['players'].items() if p['is_ai']])}）の性格に合わせた自然な発言を展開してください。"""

    async with game["channel"].typing():
        ai_reply = await call_llm(prompt)
        if ai_reply:
            if user_input:
                game["history"].append(f"人間発言: {user_input}")
            game["history"].append(ai_reply)
            await send_split_message(game["channel"], ai_reply)
        else:
            await game["channel"].send("⚠️ AI応答エラー。`!test` をお試しください。")

    if not is_watch and game["mode"] != "multi" and game["turn_count"] >= 5:
        await game["channel"].send("\n🚨 **【5ターン終了】** これより投票タイムに移ります！")
        await start_voting_phase()

# --- 投票フェーズ ---
async def start_voting_phase():
    game["phase"] = "voting"
    await game["channel"].send("🗳️ **【投票タイム】** 誰を処刑するか投票中...")

    # AIたちの自動投票
    for name, p in game["players"].items():
        if p["is_ai"]:
            candidates = [n for n in game["players"].keys() if n != name]
            if p["role"] == "人狼":
                non_wolves = [c for c in candidates if game["players"][c]["role"] != "人狼"]
                if non_wolves:
                    candidates = non_wolves
            game["votes"][name] = random.choice(candidates)

    humans = [n for n, p in game["players"].items() if not p["is_ai"]]
    
    # 人間がいない（観戦モード）または全員投票完了なら即開票
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
    if len(executed) == 1:
        executed_player = executed[0]
        res_msg += f"最多得票により、**【{executed_player}】** が処刑されました！\n"
    else:
        executed_player = None
        res_msg += f"票が割れたため、**【平和村（処刑なし）】** となりました！\n"

    werewolves = [n for n, p in game["players"].items() if p["role"] == "人狼"]
    
    res_msg += "\n🎉 **【勝敗発表】**\n"
    if executed_player and game["players"][executed_player]["role"] == "人狼":
        res_msg += "🏆 **市民陣営の勝利！**（人狼を処刑できました！）\n"
    elif not executed_player and len(werewolves) == 0:
        res_msg += "🏆 **市民陣営の勝利！**（平和村達成！）\n"
    else:
        res_msg += "🐺 **人狼陣営の勝利！**（人狼の逃げ切り成功！）\n"

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

    # --- 0. 接続診断 ---
    if content == '!test':
        async with message.channel.typing():
            res = await call_llm("「テスト成功」とだけ返答してください。", debug=True)
            await send_split_message(message.channel, res)
        return

    # --- 1. 雑談 (`!chat`) ---
    if content.startswith('!chat'):
        chat_msg = content[5:].strip()
        if not chat_msg:
            await message.reply("💬 `!chat こんにちは` と話しかけてね！")
            return
        async with message.channel.typing():
            reply = await call_llm(f"ユーザー（{message.author.display_name}）の言葉に親しく答えてください:\n{chat_msg}")
            if reply:
                await send_split_message(message.channel, reply)
        return

    # --- 2. DM処理 ---
    if isinstance(message.channel, discord.DMChannel):
        player_name = message.author.display_name
        if content.startswith('!fortune') and game["is_running"]:
            target = content[8:].strip()
            if target == "墓場":
                await message.reply(f"🔮 墓場は『{game['center_cards'][0]}』と『{game['center_cards'][1]}』です。")
            elif target in game["players"]:
                await message.reply(f"🔮 {target} さんの役職は『{game['players'][target]['role']}』です。")
            return

        if content.startswith('!steal') and game["is_running"]:
            target = content[6:].strip()
            if target in game["players"] and target != player_name:
                game["players"][player_name]["role"], game["players"][target]["role"] = game["players"][target]["role"], game["players"][player_name]["role"]
                await message.reply(f"🎭 {target} さんと交換しました。新役職: 『{game['players'][player_name]['role']}』")
            return

        if content.startswith('!vote') and game["phase"] == "voting":
            target = content[5:].strip()
            if target in game["players"]:
                game["votes"][player_name] = target
                await message.reply(f"✅ **{target}** さんに投票しました！")
                humans = [n for n, p in game["players"].items() if not p["is_ai"]]
                if all(h in game["votes"] for h in humans):
                    await Tally_and_finish()
            return

    # --- 3. 人狼コマンド (`!jinro`) ---
    if content.startswith('!jinro'):
        args = content[6:].strip().split()
        sub_cmd = args[0] if len(args) > 0 else ""

        if sub_cmd in ['clear', 'リセット']:
            if game["discussion_task"]:
                game["discussion_task"].cancel()
            game = {"is_running": False, "mode": None, "phase": "idle", "channel": None, "players": {}, "center_cards": [], "votes": {}, "turn_count": 0, "discussion_task": None, "history": []}
            await message.reply('🔄 ゲーム状態をリセットしました！')
            return

        # 🍿 観戦モード起動
        if sub_cmd in ['watch', '観戦']:
            await setup_game(message.channel, "watch")
            return

        if sub_cmd == "solo":
            await setup_game(message.channel, "solo", [message.author])
            return

        if sub_cmd in ["start", "multi"]:
            mentions = message.mentions
            human_players = [message.author] + mentions
            mode_type = "solo" if len(human_players) == 1 else "multi"
            await setup_game(message.channel, mode_type, human_players)
            return

        if game["is_running"] and game["phase"] == "discussion" and game["mode"] != "watch":
            user_msg = content[6:].strip() or "（ゲームを進めてください）"
            await generate_ai_discussion(user_input=f"{message.author.display_name}: {user_msg}")

client.run(DISCORD_TOKEN)
