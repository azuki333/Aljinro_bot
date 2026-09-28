import discord
import urllib.request
import urllib.error
import json
import time
import asyncio
import os
import random

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# --- AIキャラクター設定 ---
AI_CHARACTERS = [
    {"name": "レン", "desc": "20代男性。冷静沈着で論理的。理由を深掘りして詰めるタイプ。"},
    {"name": "ユイ", "desc": "17歳女子高生。直感重視で天然だが、直感で真実を突く。言動が感情的。"},
    {"name": "Gemini-A", "desc": "Googleの刺客。確率とログ分析重視。長文で客観的なロジックを展開する。"},
    {"name": "Gemini-B", "desc": "Googleの刺客。人間の心理や発言の矛盾を鋭く突き、誘導やブラフも使う。"},
    {"name": "タクミ", "desc": "30代ベテラン。他人に振って様子を見たり、盤面を混乱させたりするのが得意。"}
]

# --- 役職定義 (5人プレイ: 計7枚) ---
ROLES_POOL = ["人狼", "人狼", "占い師", "怪盗", "市民", "市民", "市民"]

# --- ゲーム状態管理 ---
game = {
    "is_running": False,
    "mode": None,          # "ai", "solo", "multi"
    "phase": "idle",       # "night", "discussion", "voting", "ended"
    "channel": None,
    "players": {},         # name -> {"is_ai": True/False, "user_obj": User/None, "role": "", "original_role": ""}
    "center_cards": [],    # 墓場のカード2枚
    "votes": {},           # voter -> target
    "turn_count": 0,
    "discussion_task": None,
    "history": []          # 発言ログ（直近10通を保持して対話に利用）
}

# --- Discordへの自動分割送信処理（2000文字対策） ---
async def send_split_message(channel, content):
    if not content:
        return
    # Discordの制限は2000文字（余裕をもって1900文字単位で分割）
    chunk_size = 1900
    for i in range(0, len(content), chunk_size):
        await channel.send(content[i:i+chunk_size])

# --- LLM呼出関数 ---
def call_llm(prompt_content):
    # 1. Gemini
    if GEMINI_API_KEY:
        try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt_content}]}]}
            req = urllib.request.Request(gemini_url, data=json.dumps(payload).encode('utf-8'), headers=HTTP_HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=12.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "candidates" in data and len(data["candidates"]) > 0:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    if len(text) > 10:
                        return text
        except Exception as e:
            print(f"Gemini Error: {e}")

    # 2. OpenAI (Fallback)
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
            with urllib.request.urlopen(req, timeout=12.0) as res:
                data = json.loads(res.read().decode('utf-8'))
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"OpenAI Error: {e}")

    return None

@client.event
async def on_ready():
    print(f'🤖 【ワンナイト人狼GM Bot】起動成功！ ({client.user.name})')

# --- 5分タイマー処理 ---
async def start_5min_timer():
    await asyncio.sleep(300)
    if game["is_running"] and game["phase"] == "discussion":
        await game["channel"].send("🚨 **【5分経過・議論終了！】** 🚨\nタイムアップです！これより投票タイムに移ります。")
        await start_voting_phase()

# --- ゲームセットアップ ---
async def setup_game(channel, mode, human_users):
    global game
    game["is_running"] = True
    game["mode"] = mode
    game["phase"] = "night"
    game["channel"] = channel
    game["players"] = {}
    game["votes"] = {}
    game["turn_count"] = 0
    game["history"] = []

    all_participants = []
    
    for u in human_users:
        all_participants.append({"name": u.display_name, "is_ai": False, "user_obj": u})

    # 5人に足りない分をAIで補充
    needed_ai_count = 5 - len(all_participants)
    if needed_ai_count > 0:
        selected_ais = random.sample(AI_CHARACTERS, needed_ai_count)
        for ai in selected_ais:
            all_participants.append({"name": ai["name"], "is_ai": True, "user_obj": None, "desc": ai["desc"]})

    # 役職シャッフル
    shuffled_roles = random.sample(ROLES_POOL, len(ROLES_POOL))
    game["center_cards"] = [shuffled_roles.pop(), shuffled_roles.pop()] # 墓場2枚

    for p in all_participants:
        assigned_role = shuffled_roles.pop()
        game["players"][p["name"]] = {
            "is_ai": p["is_ai"],
            "user_obj": p["user_obj"],
            "role": assigned_role,
            "original_role": assigned_role,
            "desc": p.get("desc", "")
        }

    ai_names = [n for n, p in game["players"].items() if p["is_ai"]]
    ai_status_msg = f"（AIプレイヤー: {', '.join(ai_names)} が参戦）" if ai_names else "（人間5人での対戦）"

    await channel.send(
        f"🌌 **【ワンナイト人狼】ゲームを開始します！】**\n"
        f"参加者: **{', '.join(game['players'].keys())}** {ai_status_msg}\n"
        f"現在『夜の時間』です。人間プレイヤーに個別DMで役職を通知しています…"
    )

    await process_night_phase()

# --- 夜の処理 ---
async def process_night_phase():
    werewolves = [name for name, p in game["players"].items() if p["role"] == "人狼"]

    # 人間への個別DM
    for name, p in game["players"].items():
        if not p["is_ai"] and p["user_obj"]:
            msg = f"🌙 **【あなたの役職】: 『{p['role']}』**\n"
            if p["role"] == "人狼":
                other_wolves = [w for w in werewolves if w != name]
                if other_wolves:
                    msg += f"仲間となる人狼は **【{', '.join(other_wolves)}】** です。"
                else:
                    msg += "あなた以外の仲間はいません（孤独な人狼です）。"
            elif p["role"] == "占い師":
                msg += "夜の能力を行使できます！誰か1人の役職を見るか、墓場のカード2枚を見るか選んでください。\n"
                msg += "💬 **DMで `!fortune プレイヤー名` または `!fortune 墓場` と送信してください。**"
            elif p["role"] == "怪盗":
                msg += "誰か1人と役職を交換できます。\n"
                msg += "💬 **DMで `!steal プレイヤー名` と送信してください。（交換しない場合は `!steal なし`）**"
            elif p["role"] == "市民":
                msg += "特別な能力はありません。昼の議論で村を導いてください！"
            
            try:
                await p["user_obj"].send(msg)
            except Exception as e:
                await game["channel"].send(f"⚠️ {name} さんへのDM送信に失敗しました。DMの設定をご確認ください。")

    # AIの夜行動（自動判定）
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
                    p["ai_knows"] = f"{target} さんと役職を交換しました。あなたの新しい役職は『{game['players'][name]['role']}』です。"
                else:
                    p["ai_knows"] = "役職の交換を行いませんでした。"

    await game["channel"].send("☀️ **朝になりました！全員目を開けてください。**\nこれより議論タイムを開始します。")
    game["phase"] = "discussion"

    if game["mode"] == "multi":
        await game["channel"].send("⏱️ **【制限時間: 5分】** 自由にご議論ください！\n※AIプレイヤーへ呼びかける場合は `!jinro 発言内容` で打つと返答します。")
        game["discussion_task"] = asyncio.create_task(start_5min_timer())
    else:
        await game["channel"].send("💬 **【全5ターン制】** 発言ごとにAIたちが応答します。`!jinro 発言内容` で発言してください。")
        await generate_ai_discussion("（朝が来ました。ゲームが始まりました。自己紹介や怪しい点について議論を開始してください。）")

# --- AI議論生成 ---
async def generate_ai_discussion(user_input=""):
    if game["phase"] != "discussion":
        return

    game["turn_count"] += 1
    
    ai_players_info = []
    for name, p in game["players"].items():
        if p["is_ai"]:
            knows = p.get("ai_knows", "特別な夜の情報はありません。")
            ai_players_info.append(f"- {name} ({p['desc']}): 元の役職『{p['original_role']}』, 現在の役職『{p['role']}』. 夜の知識: {knows}")

    # 直近10通分（最大10個）の記憶を取り出す
    recent_history = game["history"][-10:] if len(game["history"]) >= 10 else game["history"]

    prompt = f"""あなたは「ワンナイト人狼」のAIプレイヤーたちを演じる高度なGMです。
以下の【過去10通の会話ログ】を踏まえて、対話がしっかり噛み合うようにAIプレイヤーたちの議論を生成してください。

【ゲームモード】: {game['mode']}
【現在のターン】: {game['turn_count']} / 5 ターン

【AIプレイヤーの秘密情報（思考のベースとし、不用意にネタバレしないこと）】
{chr(10).join(ai_players_info)}

【直近のプレイヤー発言】
{user_input}

【直近10通の会話ログ（文脈を維持すること）】
{chr(10).join(recent_history)}

【出力・発言制限ルール（厳格遵守）】
1. AIプレイヤー（{', '.join([n for n, p in game['players'].items() if p['is_ai']])}）の発言を作成してください。
2. **全体の発言合計は、最低でも【200文字以上】の読み応えのある長さにしてください。** 1〜2文で終わらせず、各AIが疑い、反論し、推理を展開させてください。
3. 直近のプレイヤー発言やログにしっかり反応した【対話】にしてください。

フォーマット例:
レン: 「〜〜」
ユイ: 「〜〜」"""

    ai_reply = call_llm(prompt)
    if ai_reply:
        # ログへの追加
        game["history"].append(f"最新発言: {user_input}")
        game["history"].append(ai_reply)
        
        # 2,000文字超に対応した分割送信
        await send_split_message(game["channel"], ai_reply)

    if game["mode"] != "multi" and game["turn_count"] >= 5:
        await game["channel"].send("\n🚨 **【5ターン終了・議論強制打ち切り】** 🚨\n規定ターン数に達しました。これより投票タイムに移ります！")
        await start_voting_phase()

# --- 投票フェーズ ---
async def start_voting_phase():
    game["phase"] = "voting"
    await game["channel"].send("🗳️ **【投票タイム】**\n誰を処刑するか決めてください！\n・人間の方: **Botとの個別DM** で `!vote プレイヤー名` と送信してください。\n・AIは自動で秘密裏に投票完了しています。")

    # AIの自動投票
    for name, p in game["players"].items():
        if p["is_ai"]:
            candidates = [n for n in game["players"].keys() if n != name]
            if p["role"] == "人狼":
                non_wolves = [c for c in candidates if game["players"][c]["role"] != "人狼"]
                if non_wolves:
                    candidates = non_wolves
            game["votes"][name] = random.choice(candidates)

    humans = [n for n, p in game["players"].items() if not p["is_ai"]]
    if len(humans) == 0:
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

    res_msg = "⚖️ **【集計結果と開示】**\n"
    for voter, target in game["votes"].items():
        res_msg += f"・{voter} ➡️ {target}\n"

    res_msg += "\n🩸 **【処刑結果】**\n"
    if len(executed) == 1:
        executed_player = executed[0]
        res_msg += f"最多得票により、**【{executed_player}】** が処刑されました！\n"
    else:
        executed_player = None
        res_msg += f"票が割れたため（{', '.join(executed)}）、**【平和村（処刑なし）】** となりました！\n"

    werewolves = [n for n, p in game["players"].items() if p["role"] == "人狼"]
    
    res_msg += "\n🎉 **【勝敗発表】**\n"
    if executed_player and game["players"][executed_player]["role"] == "人狼":
        res_msg += "🏆 **市民陣営の勝利！**（人狼を処刑することに成功しました！）\n"
    elif not executed_player and len(werewolves) == 0:
        res_msg += "🏆 **市民陣営の勝利！**（人狼不在の村で平穏を守りました！）\n"
    else:
        res_msg += "🐺 **人狼陣営の勝利！**（人狼の逃げ切り成功です！）\n"

    res_msg += "\n📜 **【最終役職一覧】**\n"
    for n, p in game["players"].items():
        orig = f" (元: {p['original_role']})" if p['original_role'] != p['role'] else ""
        res_msg += f"・{n}: 『{p['role']}』{orig}\n"
    res_msg += f"・墓場（未配布）: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』\n"

    await send_split_message(game["channel"], res_msg)

# --- メッセージ受信イベント ---
@client.event
async def on_message(message):
    global game

    if message.author.bot:
        return

    content = message.content.strip()

    # --- DMでの夜のアクション・投票処理 ---
    if isinstance(message.channel, discord.DMChannel):
        player_name = message.author.display_name
        
        # 占い処理
        if content.startswith('!fortune'):
            target = content[8:].strip()
            if game["is_running"] and game["players"].get(player_name, {}).get("role") == "占い師":
                if target == "墓場":
                    await message.reply(f"🔮 墓場のカードは『{game['center_cards'][0]}』と『{game['center_cards'][1]}』です。")
                elif target in game["players"]:
                    await message.reply(f"🔮 {target} さんの役職は『{game['players'][target]['role']}』です。")
                else:
                    await message.reply("⚠️ 対象が見つかりません。正確なプレイヤー名か『墓場』と送信してください。")
            return

        # 怪盗処理
        if content.startswith('!steal'):
            target = content[6:].strip()
            if game["is_running"] and game["players"].get(player_name, {}).get("role") == "怪盗":
                if target in game["players"] and target != player_name:
                    game["players"][player_name]["role"], game["players"][target]["role"] = game["players"][target]["role"], game["players"][player_name]["role"]
                    await message.reply(f"🎭 {target} さんと役職を交換しました！あなたの新しい役職は『{game['players'][player_name]['role']}』です。")
                elif target in ["なし", "スキップ"]:
                    await message.reply("🎭 役職の交換を行いませんでした。")
                else:
                    await message.reply("⚠️ 交換対象が見つかりません。正確なプレイヤー名を送信してください。")
            return

        # 投票処理
        if content.startswith('!vote'):
            target = content[5:].strip()
            if game["phase"] == "voting" and player_name in game["players"]:
                if target in game["players"]:
                    game["votes"][player_name] = target
                    await message.reply(f"✅ **{target}** さんに投票完了しました！")

                    # 人間全員の投票チェック
                    human_names = [n for n, p in game["players"].items() if not p["is_ai"]]
                    if all(h in game["votes"] for h in human_names):
                        await Tally_and_finish()
                else:
                    await message.reply("⚠️ 対象のプレイヤー名が見つかりません。正確に入力してください。")
            return

    # --- ギルドチャンネルでのコマンド処理 ---
    if content.startswith('!jinro'):
        args = content[6:].strip().split()
        sub_cmd = args[0] if len(args) > 0 else ""

        # リセット
        if sub_cmd in ['clear', 'リセット']:
            if game["discussion_task"]:
                game["discussion_task"].cancel()
            game = {"is_running": False, "mode": None, "phase": "idle", "channel": None, "players": {}, "center_cards": [], "votes": {}, "turn_count": 0, "discussion_task": None, "history": []}
            await message.reply('🔄 ゲーム状態を完全リセットしました！')
            return

        # 観戦モード (`!jinro ai`)
        if sub_cmd == "ai":
            await setup_game(message.channel, "ai", [])
            return

        # ソロモード (`!jinro solo`)
        if sub_cmd == "solo":
            await setup_game(message.channel, "solo", [message.author])
            return

        # マルチ対戦 (`!jinro start @友達1 @友達2`)
        if sub_cmd in ["start", "multi"]:
            mentions = message.mentions
            if len(mentions) < 1:
                await message.reply("⚠️ 一緒に遊ぶ友達を1〜4人メンションしてください！\n例: `!jinro start @User1 @User2`")
                return
            
            human_players = [message.author] + mentions
            
            if len(human_players) > 5:
                await message.reply("⚠️ 5人制ゲームのため、プレイヤーは最大5人までです。（あなた＋メンション4人まで）")
                return

            mode_type = "solo" if len(human_players) == 1 else "multi"
            await setup_game(message.channel, mode_type, human_players)
            return

        # 通常発言（対話応答）
        if game["is_running"] and game["phase"] == "discussion":
            user_msg = content[6:].strip()
            if not user_msg:
                user_msg = "（ゲームを進めてください）"
            
            if game["mode"] != "multi":
                async with message.channel.typing():
                    await generate_ai_discussion(f"{message.author.display_name}: {user_msg}")

client.run(DISCORD_TOKEN)
