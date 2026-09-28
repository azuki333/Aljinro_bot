import discord
import requests
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

# 【昨日の約束】最新10通分の会話履歴を記憶しておくための無敵の配列スタック
conversation_history = []

# 【ロック絶対回避システム】APIの連続連打（Rate Limit）を防ぐためのクールダウン制御
last_api_call_time = 0
API_COOLDOWN_MS = 3.0  # 3秒以内の連打は自動で弾いてロックを絶対回避します

# 【昨日の約束】ゲームのモードに応じた進行管理ステート
game_state = {
    "is_running": False,
    "mode": "turn",       # "turn"（5ターン制）か "time"（5分タイマー制）
    "turn_count": 0       # 現在のターン数（AI対戦用）
}

game_timer_task = None

@client.event
async def on_ready():
    print('🤖 【5ターン×5分タイマー完全分離版】対話型ワンナイトBot、完全起動！')

# 人間同士で遊ぶときの5分間（300秒）の議論制限タイマー処理
async def start_game_timer(channel):
    global game_state
    await asyncio.sleep(300) 
    if game_state["is_running"] and game_state["mode"] == "time":
        await channel.send('🚨 🚨 🚨 【5分経過・議論強制終了】 🚨 🚨 🚨\n\n主様、人間同士の極限の議論時間（300秒）が終了しました！これ以上のおしゃべりは禁止です！\n生存者のプレイヤーたちは、今すぐ各自の決め打ちで投票を投じて、最後の結果を開票してください！')
        game_state["is_running"] = False

@client.event
async def on_message(message):
    global conversation_history, last_api_call_time, game_state, game_timer_task
    
    if message.author.bot:
        return

    # 主様がいつもの「!jinro」と打つだけで100%完璧に応答します！
    if message.content.startswith('!jinro'):
        user_prompt = message.content[6:].strip()
        
        # コマンド !jinro リセット が送られたら記憶と状態を綺麗に消去します
        if user_prompt == 'clear' or user_prompt == 'リセット':
            conversation_history = []
            game_state = {"is_running": False, "mode": "turn", "turn_count": 0}
            if game_timer_task:
                game_timer_task.cancel()
                game_timer_task = None
            await message.reply('🔄 秘密基地の記憶と進行中のゲームを完全にリセットしたよ！新しい試合を始めておくれ！')
            return

        # 【ロック絶対回避チェック】
        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 主様、落ち着いて！24時間ロックの罠を回避するために、3秒だけおいてからもう一度送っておくれ！')
            return
        last_api_call_time = current_time

        # 【昨日の約束：ゲーム開始時のモード判定】
        if 'ゲーム開始' in user_prompt or 'スタート' in user_prompt or '対戦開始' in user_prompt:
            game_state["is_running"] = True
            conversation_history = []
            
            # 「人間同士」や「友達」という言葉が入っている時だけ【5分タイマー制】にする
            if '人間同士' in user_prompt or '友達' in user_prompt:
                game_state["mode"] = "time"
                game_state["turn_count"] = 0
                if game_timer_task: game_timer_task.cancel()
                game_timer_task = asyncio.create_task(start_game_timer(message.channel))
            else:
                # 【AIと私】【AI同士】の時は、絶対に【5ターン制】に固定します！
                game_state["mode"] = "turn"
                game_state["turn_count"] = 0

        # 【5ターン制のカウントチェック】
        if game_state["is_running"] and game_state["mode"] == "turn":
            game_state["turn_count"] += 1
            if game_state["turn_count"] > 5:
                await message.reply('🗳️ 【5ターン制限終了】議論数は終了したよ！今すぐ各自の決め打ちで投票を投じて、最後の結果を開票しておくれ！')
                game_state["is_running"] = False
                return

        try:
            async with message.channel.typing():
                # 今回の新しい発言を、最新10通の記憶配列に追加
                conversation_history.append({"role": "user", "content": f"{message.author.name}: {user_prompt if user_prompt else '（ゲーム開始の合図）'}"})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                # 【昨日の約束】ChatGPT側のガチガチのキャラクター性格設定（Geminiは性格不要）
                current_mode_text = f"【現在の議論ターン数: {game_state['turn_count']} / 5 ターン】" if game_state["mode"] == "turn" else "【人間同士の5分間時間制限バトル中】"
                
                system_content = f"""あなたは最高に面白い「対話型ワンナイト人狼ゲーム」を主様（ユーザー）と一緒にリアルタイムに進行するAIGM（人工知能ゲームマスター）です。
                これは小説の自動生成ではなく、主様が1人のプレイヤーとして参加する【本物の対話型の試合】です。
                {current_mode_text}
                
                主様の発言、および最新10通分の過去のチャットの文脈を完璧に記憶して引き継ぎ、
                以下の4匹。AIプレイヤーの個性をむき出しにして、人間の言葉に対して「1通ずつリアルタイムにチャットで殴り返す」ように返答ログを生成してください。
                最大5ターン（または人間同士なら制限時間5分）で議論が綺麗に詰むように、会話をどんどん白熱させていくこと。暴言は1文字も禁止です。
                
                【参戦する4大AIプレイヤーの設定】
                1. ChatGPT-A（OpenAIの刺客・20代クール男子）：
                   常に冷静沈着、理路整然としたロジックで相手を追い詰める。感情をあまり表に出さないが、鋭い観察眼で嘘や怪盗のブーメランハメ技を一瞬で見抜いて冷徹に突き刺す、統率のブレイン。
                2. ChatGPT-B（OpenAIの刺客・17歳の女の子）：
                   おっとりしていて、一見ルールがあまり分かっていないような天然な女の子。しかし、その無邪気なパッション（熱量）や突拍子もない一言が、クールな数式ルートを物理的にバグらせて引っかき回す、恐ろしいポテンシャルを持つ。
                3. Gemini-A（Googleの刺客・性格なし）：ロジックと確率をもとにフラットにチャット発言する。
                4. Gemini-B（Googleの刺客・性格なし）：ロジックと確率をもとにフラットにチャット発言する。"""

                ai_reply = ""
                gemini_failed = False

                # 【昨日の約束：Gemini混雑隠し＆フォールバック処理】
                if GEMINI_API_KEY:
                    try:
                        gemini_url = f"https://googleapis.com{GEMINI_API_KEY}"
                        gemini_payload = {
                            "contents": [{"parts": [{"text": system_content + "\n\nこれまでの会話履歴の流れを完璧に引き継いで、次のワンナイト人狼の議論ログを出力してください。\n\n【会話履歴】\n" + json.dumps(conversation_history, ensure_ascii=False)}]}]
                        }
                        gemini_res = requests.post(gemini_url, json=gemini_payload, timeout=4.0)
                        gemini_data = gemini_res.json()
                        if gemini_res.status_code == 200 and "candidates" in gemini_data:
                            ai_reply = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                        else:
                            gemini_failed = True
                    except:
                        gemini_failed = True

                # Geminiが未設定、または混雑・エラー時は、100%完全にChatGPT（OpenAI）側がすべての役割と5人の数合わせを引き取って自動代行
                if not GEMINI_API_KEY or gemini_failed or not ai_reply:
                    openai_headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
                    openai_payload = {
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "system", "content": system_content}] + conversation_history,
                        "temperature": 0.85
                    }
                    openai_res = requests.post("https://openai.com", headers=openai_headers, json=openai_payload)
                    openai_data = openai_res.json()
                    if openai_res.status_code != 200:
                        raise Exception(openai_data.get("error", {}).get("message", "OpenAI API Error"))
                    ai_reply = openai_data["choices"][0]["message"]["content"]

                # AIの今回のチャット返答も、次の会話のために記憶の配列に追加
                conversation_history.append({"role": "assistant", "content": ai_reply})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                # 5ターン目（最終ターン）の時は、チャットの最後に投票を促すアナウンスを自動でドッキング
                if game_state["is_running"] and game_state["mode"] == "turn" and game_state["turn_count"] == 5:
                    ai_reply += "\n\n🚨 🚨 🚨 【5ターン到達・議論強制終了】 🚨 🚨 🚨\n主様、5ターンの極限対戦議論が終了しました！これ以上のおしゃべりは禁止です！\n生存者のプレイヤーたちは、今すぐ各自の決め打ちで投票（開票）を行ってください！"
                    game_state["is_running"] = False

                await message.reply(ai_reply)

        except Exception as error:
            print(error)
            await message.reply(f'⚠️ [System Error] OpenAI API Connection Failed. Reason: {error}')

# Botをログインさせます
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
