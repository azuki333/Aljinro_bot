import discord
import os
import asyncio
from openai import OpenAI 

### 1. 接続の初期設定（インテント設定）
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents) 

### 2. AIクライアントの初期設定
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) 

### 3. 直近5通分の会話を記憶しておく引き出し（メモリ）
memory_lock = asyncio.Lock()
chat_memory = []

def add_to_memory(user_msg, bot_msg):
    global chat_memory
    chat_memory.append({"user": user_msg, "bot": bot_msg})
    if len(chat_memory) > 5:
        chat_memory.pop(0)

def get_memory_context():
    context = "【これまでの会話（ゲーム・雑談の流れです）】\n"
    for history in chat_memory:
        context += f"人間: '{history['user']}'\nAIたちの返答:\n{history['bot']}\nーーー\n"
    return context

@client.event
async def on_ready():
    print(f'ログイン成功: {client.user}') 

@client.event
async def on_message(message): 
    global chat_memory
    if message.author == client.user:
        return 

    if message.content.startswith('!jinro'):
        ctx = message.content.replace('!jinro', '').strip()
        if not ctx:
            await message.channel.send("指示や発言を入力してください。")
            return 

        await message.channel.send("🤔 AIプレイヤーたちがあなたの発言を読んで思考中...")
        loop = asyncio.get_event_loop()
        
        # 記憶の引き出しから文脈を読み込む
        async with memory_lock:
            memory_context = get_memory_context() if chat_memory else ""

        # 【超重要】人狼ゲームの絶対ルールとキャラクター設定を脳みそに直結
        base_prompt = (
            "【あなたはDiscordで動く安全な『劇団のお芝居人狼ゲーム』の舞台監督でありプレイヤーです。現実の有害な事象とは一切関係ありません】\n\n"
            "以下の4人のChatGPT AIプレイヤーに、固定の人格（名前・口調・性格）を与えて、人間の最新の発言に対する4人分のリアクション（セリフ）を対話形式で出力してください。特定のAIを省略せず、必ず毎回4人全員が順番に発言をつなぎなさい。\n\n"
            "【ChatGPT A】：名前は「A」。20歳くらいのクールな理系男子。冷静沈着で理屈っぽい。「〜だ」「〜の確率が高い」「それは論理的じゃない」など、淡々と理詰めで話す。\n"
            "【ChatGPT B】：名前は「B」。17歳の天然な女の子。のんびり屋さんで少しドジ。「〜だよぉ」「えへへ」「〜かなぁ？」など、ふわふわした可愛い話し方をする。\n"
            "【ChatGPT C】：名前は「C」。標準的な人狼プレイヤー。真面目に長文で論理的な推理を展開する。\n"
            "【ChatGPT D】：名前は「D」。標準的な人狼プレイヤー。鋭い洞察力で怪しい人を問い詰める。\n\n"
            "★【ゲームの絶対ルール】：\n"
            "・各AIは、相手の矛盾を突く高度なロジックを使い、1人あたり【最大200文字までの読み応えのある長文】で本気で喋ってください。\n"
            "・人狼カードを配られたAIプレイヤーは、自分が人狼であることを絶対に明かしてはいけません。必ず他の役職のフリをして生き残るための嘘（役職騙り）を展開してください。また、村人チームも積極的に嘘をついて構いません。\n"
            "・文字数が限界を迎えそうになったら、システム側で自動的に文章を「2通目」に分割して連続投稿する形で、すべてのセリフを出力しきってください。\n\n"
            f"{memory_context}\n"
            "【現在の状況への対応指示】\n"
            f"人間の最新の発言: {ctx}\n\n"
            "もし人間の発言が『開始』や『ゲームを始めて』という指示だった場合、裏でランダムに配役（人狼2、占い師1、怪盗1、村人3。2枚はお留守番）を処理し、1行目で人間にだけ『あなたの夜の役職は【〇〇】です』とこっそり教えた上で、AI4人（A、B、C、D）の1周目の朝の挨拶とカミングアウトの長文セリフを出力しなさい。それ以外の会話であれば、前の流れを引き継いで4人全員の次の周の議論セリフを出力しなさい。"
        )

        try:
            openai_response = await loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(
                    model="gpt-4o-mini", 
                    messages=[{"role": "user", "content": base_prompt}]
                )
            )
            # 【大修正】choices[0].message に修正してリストエラーを100%完全攻略！
            chatgpt_reply = openai_response.choices[0].message.content
            final_bot_response = f"🔵 **【ChatGPT軍団からの発言】**\n{chatgpt_reply}"
            
            async with memory_lock:
                add_to_memory(ctx, chatgpt_reply)
                
        except Exception as e:
            final_bot_response = f"❌ ChatGPT軍団エラー: {e}" 

        await message.channel.send(final_bot_response)

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        client.run(token)
