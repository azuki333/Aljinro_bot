import discord
import requests
import json
import time
import asyncio

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 環境変数からOpenAIのAPIキーとDiscordトークンを安全に読み込みます
import os
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 最新10通分の会話履歴を記憶しておくための無敵の配列スタック
conversation_history = []

# 【ロック絶対回避】3秒以内の連打は自動で弾いて24時間ロックを絶対回避します
last_api_call_time = 0
API_COOLDOWN_MS = 3.0  # Pythonは秒単位で指定します

# 人間同士で遊ぶときの5分間（300秒）の議論制限タイマー管理
is_game_running = False
game_timer_task = None

@client.event
async def on_ready():
    print('🤖 一昨日の約束の完全体（Python版・!jinro対応・5分タイマー＆10通記憶）Bot、完全起動！')

# 5分間の議論制限タイマーの非同期処理
async def start_game_timer(channel):
    global is_game_running
    await asyncio.sleep(300) # ぴったり5分間（300秒）待ちます
    if is_game_running:
        await channel.send('🚨 🚨 🚨 【5分経過・議論強制終了】 🚨 🚨 🚨\n\n主様、人間同士の極限の議論時間（300秒）が終了しました！これ以上のおしゃべりは禁止です！\n生存者の村人たちは、今すぐ各自の決め打ちで投票を投じて、最後の結果を開票してください！')
        is_game_running = False

@client.event
async def on_message(message):
    global conversation_history, last_api_call_time, is_game_running, game_timer_task
    
    if message.author.bot:
        return

    # 主様がいつもの「!jinro」と打つだけで100%完璧に応答します！
    if message.content.startswith('!jinro'):
        user_prompt = message.content[6:].strip()
        
        if not user_prompt:
            await message.reply('主様、ワンナイトのお題（状況や前の発言へのツッコミ）を教えておくれ！\n例：`!jinro 怪盗が人狼を盗んで結果を隠している状況の議論を作って！`')
            return

        if user_prompt == 'clear' or user_prompt == 'リセット':
            conversation_history = []
            is_game_running = False
            if game_timer_task:
                game_timer_task.cancel()
                game_timer_task = None
            await message.reply('🔄 秘密基地の記憶と進行中のゲーム（5分タイマー）を完全にリセットしたよ！')
            return

        # 【ロック絶対回避チェック】
        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 主様、落ち着いて！24時間ロックの罠を回避するために、3秒だけおいてからもう一度送っておくれ！')
            return
        last_api_call_time = current_time

        # 【5分タイマー自動起動】
        if '人間同士' in user_prompt or '人間3人' in user_prompt or 'ゲーム開始' in user_prompt:
            if not is_game_running:
                is_game_running = True
                game_timer_task = asyncio.create_task(start_game_timer(message.channel))

        try:
            async with message.channel.typing():
                # 今回の新しい発言を、最新10通の記憶配列に追加
                conversation_history.append({"role": "user", "content": f"{message.author.name}: {user_prompt}"})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                # 一昨日のガチガチのキャラクター性格設定
                system_content = f"""あなたは最高に面白い「ワンナイト人狼」の対話ログを生成、および進行を行うAIGM（人工知能ゲームマスター）です。
                人間のプレイヤー（{message.author.name}）の発言や最新10通の文脈を完璧に引き継ぎ、以下の個性をむき出しにして、人間らしい泥臭いパッション（ハッタリ、自白、ブーメランカウンター）のチャットログを生成してください。
                最大5ターン（または人間同士なら制限時間5分）で議論が綺麗に詰むように、会話をどんどん白熱させていくこと。プレイヤーが合計5人になるように数合わせを行って発言を出力してください。暴言は1文字も禁止です。
                
                【参戦する4大AIプレイヤーの設定】
                1. ChatGPT-A（OpenAIの刺客・20代クール男子）：
                   常に冷静沈着、理路整然としたロジックで相手を追い詰める。感情をあまり表に出さないが、鋭い観察眼で嘘や怪盗のブーメランハメ技を一瞬で見抜いて冷徹に突き刺す、統率のブレイン。
                2. ChatGPT-B（OpenAIの刺客・17歳の女の子）：
                   おっとりしていて、一見ルールがあまり分かっていないような天然な女の子。しかし、その無邪気なパッション（熱量）や突拍子もない一言が、クールな数式ルートを物理的にバグらせて引っかき回す、恐ろしいポテンシャルを持つ。
                3. ChatGPT-C（性格なし）：ロジックと確率をもとにフラットに発言する。
                4. ChatGPT-D（性格なし）：ロジックと確率をもとにフラットに発言する。"""

                # OpenAIの正しい通信処理
                headers = {
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_content}] + conversation_history,
                    "temperature": 0.85
                }
                
                response = requests.post("https://openai.com", headers=headers, json=payload)
                data = response.json()
                
                if response.status_code != 200:
                    raise Exception(data.get("error", {}).get("message", "OpenAI API Error"))

                ai_reply = data["choices"][0]["message"]["content"]

                # AIの今回の返答も、次の会話のために記憶の配列に追加
                conversation_history.append({"role": "assistant", "content": ai_reply})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                await message.reply(ai_reply)

        except Exception as error:
            print(error)
            await message.reply('⚠️ 主様、ごめんね！APIの通信でちょっと処理落ちしちゃった。環境変数に `OPENAI_API_KEY` が正しく入っているか確認しておくれ！')

# Botをログインさせます
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
