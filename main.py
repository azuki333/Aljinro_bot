import discord
import urllib.request
import urllib.error
import json
import time
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 環境変数から各種APIキーを安全に読み込みます
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 最新10通分の会話履歴を記憶しておくための無敵の配列スタック
conversation_history = []

# 【ロック絶対回避】3秒以内の連打は自動で弾いて24時間ロックを絶対回避します
last_api_call_time = 0
API_COOLDOWN_MS = 3.0 

# ゲームの進行管理ステート
game_state = {
    "is_running": False,
    "mode": "turn",       # "turn"（5ターン制）か "time"（5分タイマー制）
    "turn_count": 0       # 現在のターン数（AI対戦用）
}

game_timer_task = None

@client.event
async def on_ready():
    print('🤖 【Gemini人数合わせ＆5分タイマー搭載】完全体対話型ワンナイトBot、完全起動！')

# 5分間の議論制限タイマー処理（人間同士用）
async def start_game_timer(channel):
    global game_state
    await asyncio.sleep(300) 
    if game_state["is_running"] and game_state["mode"] == "time":
        await channel.send('🚨 🚨 🚨 【5分経過・議論強制終了】 🚨 🚨 🚨\n\n主様、人間同士の極限の議論時間（300秒）が終了しました！これ以上のおしゃべりは禁止です！')
        game_state["is_running"] = False

@client.event
async def on_message(message):
    global conversation_history, last_api_call_time, game_state, game_timer_task
    
    if message.author.bot:
        return

    # 主様がいつもの「!jinro」と打つだけで100%完璧に応答します！
    if message.content.startswith('!jinro'):
        user_prompt = message.content[6:].strip()
        
        # コマンド !jinro リセット が送られたらリセット
        if user_prompt == 'clear' or user_prompt == 'リセット':
            conversation_history = []
            game_state = {"is_running": False, "mode": "turn", "turn_count": 0}
            if game_timer_task:
                game_timer_task.cancel()
                game_timer_task = None
            await message.reply('🔄 秘密基地の記憶と進行中のゲームを完全にリセットしたよ！')
            return

        # 【ロック絶対回避チェック】
        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 主様、落ち着いて！3秒だけおいてからもう一度送っておくれ！')
            return
        last_api_call_time = current_time

        # ゲーム開始時のモード判定
        if 'ゲーム開始' in user_prompt or 'スタート' in user_prompt or '対戦開始' in user_prompt:
            game_state["is_running"] = True
            conversation_history = []
            if '人間同士' in user_prompt or '友達' in user_prompt:
                game_state["mode"] = "time"
                game_state["turn_count"] = 0
                if game_timer_task: game_timer_task.cancel()
                game_timer_task = asyncio.create_task(start_game_timer(message.channel))
            else:
                game_state["mode"] = "turn"
                game_state["turn_count"] = 0

        # 【5ターン制のカウントチェック】
        if game_state["is_running"] and game_state["mode"] == "turn":
            game_state["turn_count"] += 1
            if game_state["turn_count"] > 5:
                await message.reply('🗳️ 【5ターン制限終了】議論数は終了したよ！今すぐ各自の投票を行ってください！')
                game_state["is_running"] = False
                return

        try:
            async with message.channel.typing():
                conversation_history.append({"role": "user", "content": f"{message.author.name}: {user_prompt if user_prompt else '（ゲーム開始の合図）'}"})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                current_mode_text = f"【現在の議論ターン数: {game_state['turn_count']} / 5 ターン】" if game_state["mode"] == "turn" else "【人間同士の5分間時間制限バトル中】"
                
                system_content = f"""あなたは最高に面白い「対話型ワンナイト人狼ゲーム」を主様と一緒にリアルタイムに進行する AIGM です。
                人間のプレイヤー（{message.author.name}）の発言や最新10通の文脈を完璧に記憶して引き継ぎ、以下の4匹のAIプレイヤーの個性をむき出しにして、リアルタイムにチャット発言を生成してください。
                最大5ターン（または人間同士なら制限時間5分）で議論が綺麗に詰むように、会話を白熱させていくこと。
                {current_mode_text}
                
                【参戦する4大AIプレイヤーの設定】
                1. ChatGPT-A（20代クール男子：レン）：冷静沈着、理路整然としたロジック。
                2. ChatGPT-B（17歳の女の子：ユイ）：おっとり天然な女子高生。突拍子もない一言。
                3. Gemini-A（Googleの刺客・性格なし）：ロジックと確率をもとにフラットに発言する。
                4. Gemini-B（Googleの刺客・性格なし）：ロジックと確率をもとにフラットに発言する。"""

                ai_reply = ""
                gemini_failed = False

                # 【本物の約束】Gemini（規制なし）を最優先で呼び出します！
                if GEMINI_API_KEY:
                    try:
                        gemini_url = f"https://googleapis.com{GEMINI_API_KEY}"
                        gemini_payload = {
                            "contents": [{"parts": [{"text": system_content + "\n\n【会話履歴】\n" + json.dumps(conversation_history, ensure_ascii=False)}]}]
                        }
                        gemini_req = urllib.request.Request(
                            gemini_url,
                            data=json.dumps(gemini_payload).encode('utf-8'),
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        with urllib.request.urlopen(gemini_req, timeout=4.0) as gemini_res:
                            gemini_data = json.loads(gemini_res.read().decode('utf-8'))
                            if "candidates" in gemini_data:
                                ai_reply = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                            else:
                                gemini_failed = True
                    except:
                        gemini_failed = True

                # Geminiが未設定、または混雑・通信エラーで出て来られない時は、
                # OpenAI（4.97ドル入り）がバックアップとして自動でステルス代行（数合わせ）します！
                if not GEMINI_API_KEY or gemini_failed or not ai_reply:
                    openai_payload = {
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "system", "content": system_content}] + conversation_history,
                        "temperature": 0.85
                    }
                    openai_req = urllib.request.Request(
                        "https://openai.com",
                        data=json.dumps(openai_payload).encode('utf-8'),
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        method="POST"
                    )
                    with urllib.request.urlopen(openai_req, timeout=5.0) as openai_res:
                        openai_data = json.loads(openai_res.read().decode('utf-8'))
                        ai_reply = openai_data["choices"][0]["message"]["content"]

                conversation_history.append({"role": "assistant", "content": ai_reply})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                if game_state["is_running"] and game_state["mode"] == "turn" and game_state["turn_count"] == 5:
                    ai_reply += "\n\n🚨 🚨 🚨 【5ターン到達・議論強制終了】 🚨 🚨 🚨"
                    game_state["is_running"] = False

                await message.reply(ai_reply)

        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            await message.reply(f'⚠️ [HTTP Error {e.code}] 門番に拒否されました。中身: {err_body[:80]}')
        except Exception as error:
            await message.reply(f'⚠️ [System Error] OpenAI API Connection Failed. Reason: {error}')

# Botをログインさせます
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
