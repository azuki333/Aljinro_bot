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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

conversation_history = []
last_api_call_time = 0
API_COOLDOWN_MS = 3.0 

game_state = {
    "is_running": False,
    "mode": "turn",
    "turn_count": 0
}

game_timer_task = None

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

@client.event
async def on_ready():
    print('🤖 【完全体】ワンナイトBot、起動成功！')

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

    if message.content.startswith('!jinro'):
        user_prompt = message.content[6:].strip()
        
        if user_prompt in ['clear', 'リセット']:
            conversation_history = []
            game_state = {"is_running": False, "mode": "turn", "turn_count": 0}
            if game_timer_task:
                game_timer_task.cancel()
                game_timer_task = None
            await message.reply('🔄 秘密基地の記憶と進行中のゲームを完全にリセットしたよ！')
            return

        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 主様、落ち着いて！3秒だけおいてからもう一度送っておくれ！')
            return
        last_api_call_time = current_time

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

        if game_state["is_running"] and game_state["mode"] == "turn":
            game_state["turn_count"] += 1
            if game_state["turn_count"] > 5:
                await message.reply('🗳️ 【5ターン制限終了】議論数は終了したよ！今すぐ各自の投票を行ってください！')
                game_state["is_running"] = False
                return

        try:
            async with message.channel.typing():
                input_text = user_prompt if user_prompt else '（ゲーム開始！会話を始めてください）'
                current_mode_text = f"【現在の議論ターン数: {game_state['turn_count']} / 5 ターン】" if game_state["mode"] == "turn" else "【人間同士の5分間時間制限バトル中】"
                
                # 会話履歴テキストの作成
                history_text = ""
                for h in conversation_history[-6:]:  # 直近6件に制限して文脈破綻を防ぐ
                    history_text += f"{h['speaker']}: {h['text']}\n"

                # 完全一体型のプロンプト（AIが命令を無視できない構造）
                full_prompt = f"""【命令】あなたは「対話型ワンナイト人狼ゲーム」を進行する AIGM です。
必ず日本語で返答してください。挨拶（Hello等）は一切不要です。即座に人狼の議論チャットを生成してください。

【ゲーム状況】
{current_mode_text}

【参加している4人のAIプレイヤー設定】
1. レン（20代クール男子）：冷静沈着、理路整然としたロジックで追い詰める。
2. ユイ（17歳女子高生）：おっとり天然。直感で発言する。
3. Gemini-A（Googleの刺客）：確率とロジック重視。淡々と話す。
4. Gemini-B（Googleの刺客）：人間を観察し、疑い深く分析する。

【直近の会話履歴】
{history_text}

【最新のプレイヤー発言】
{message.author.name}: {input_text}

【出力指示】
上記の4人のキャラクターになりきり、{message.author.name}の発言を受けて、4人が順番に発言しているチャット会話文を作成してください。
形式例：
レン: 「〜〜」
ユイ: 「〜〜」
Gemini-A: 「〜〜」
Gemini-B: 「〜〜」"""

                ai_reply = ""
                gemini_failed = False

                # 1. Gemini API呼び出し
                if GEMINI_API_KEY:
                    try:
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                        gemini_payload = {
                            "contents": [{"parts": [{"text": full_prompt}]}]
                        }
                        gemini_req = urllib.request.Request(
                            gemini_url,
                            data=json.dumps(gemini_payload).encode('utf-8'),
                            headers=HTTP_HEADERS,
                            method="POST"
                        )
                        with urllib.request.urlopen(gemini_req, timeout=10.0) as gemini_res:
                            gemini_data = json.loads(gemini_res.read().decode('utf-8'))
                            if "candidates" in gemini_data and len(gemini_data["candidates"]) > 0:
                                ai_reply = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                            else:
                                gemini_failed = True
                    except Exception as e:
                        gemini_failed = True

                # 2. OpenAI API呼び出し（バックアップ）
                if (not ai_reply or gemini_failed) and OPENAI_API_KEY:
                    openai_url = "https://api.openai.com/v1/chat/completions"
                    openai_payload = {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": "あなたは対話型人狼ゲームのGMです。指定されたフォーマット通りに会話を生成してください。"},
                            {"role": "user", "content": full_prompt}
                        ],
                        "temperature": 0.8
                    }
                    openai_headers = HTTP_HEADERS.copy()
                    openai_headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

                    openai_req = urllib.request.Request(
                        openai_url,
                        data=json.dumps(openai_payload).encode('utf-8'),
                        headers=openai_headers,
                        method="POST"
                    )
                    with urllib.request.urlopen(openai_req, timeout=10.0) as openai_res:
                        openai_data = json.loads(openai_res.read().decode('utf-8'))
                        ai_reply = openai_data["choices"][0]["message"]["content"]

                if not ai_reply:
                    ai_reply = "⚠️ AIからの応答を取得できませんでした。APIキーの設定を確認してください。"

                # 会話履歴に保存
                conversation_history.append({"speaker": message.author.name, "text": input_text})
                conversation_history.append({"speaker": "AI_GM", "text": ai_reply})

                if game_state["is_running"] and game_state["mode"] == "turn" and game_state["turn_count"] == 5:
                    ai_reply += "\n\n🚨 🚨 🚨 【5ターン到達・議論強制終了】 🚨 🚨 🚨"
                    game_state["is_running"] = False

                await message.reply(ai_reply)

        except Exception as error:
            await message.reply(f'⚠️ [System Error] エラーが発生しました: {error}')

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
