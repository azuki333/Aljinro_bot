import os
import discord
from game_logic import game, reset_game_state, RoleCountSelectView, handle_jinro_command, Tally_and_finish

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()
    is_dm = isinstance(message.channel, discord.DMChannel)
    author_name = message.author.display_name

    # 1. ゲーム開始コマンド
    if content.startswith("!jinro start") or content.startswith("!jinro multi"):
        if game["is_running"]:
            await message.channel.send("⚠️ すでにゲームが実行中です。")
            return
        reset_game_state()
        human_users = [message.author]
        view = RoleCountSelectView("multi", human_users)
        await message.channel.send("🎴 役職構成を選択してください。", view=view)
        return

    # 2. 夜の行動コマンド（怪盗の !steal など）
    if game["phase"] == "night" and game["is_running"]:
        my_player_name = None
        for n, p in game["players"].items():
            if not p["is_ai"] and p["user_obj"] and p["user_obj"].id == message.author.id:
                my_player_name = n
                break
        
        if my_player_name:
            player_data = game["players"][my_player_name]
            
            # 🕵️ 怪盗 (!steal プレイヤー名)
            if content.startswith("!steal "):
                if player_data["role"] != "怪盗":
                    await message.author.send("あなたは怪盗ではありません！")
                    return
                target_name = content[7:].strip()
                if target_name not in game["players"] or target_name == my_player_name:
                    await message.author.send("⚠️ 有効なプレイヤー名を指定してください。")
                    return
                
                # 役職を入れ替える処理
                target_data = game["players"][target_name]
                old_role = player_data["role"]
                player_data["role"] = target_data["role"]
                target_data["role"] = old_role
                
                await message.author.send(f"🕵️ **{target_name}** から役職を盗みました！ あなたの新しい役職は 『{player_data['role']}』 です。")
                return

            # 🔮 占い師 (!fortune)
            elif content.startswith("!fortune "):
                if player_data["role"] != "占い師":
                    await message.author.send("あなたは占い師ではありません！")
                    return
                target = content[9:].strip()
                if target == "墓場" or target == "センター":
                    await message.author.send(f"🔮 墓場のカード: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』")
                elif target in game["players"] and target != my_player_name:
                    await message.author.send(f"🔮 {target} の役職は 『{game['players'][target]['role']}』 です。")
                else:
                    await message.author.send("⚠️ 有効なプレイヤー名か「墓場」を指定してください。")
                return

            # 🎯 狩人 (!hunt)
            elif content.startswith("!hunt "):
                if player_data["role"] != "狩人":
                    await message.author.send("あなたは狩人ではありません！")
                    return
                target_name = content[6:].strip()
                if target_name in game["players"] and target_name != my_player_name:
                    game["hunter_targets"][my_player_name] = target_name
                    await message.author.send(f"🎯 {target_name} を道連れ対象に指定しました。")
                else:
                    await message.author.send("⚠️ 有効なプレイヤー名を指定してください。")
                return

            # 🧙‍♀️ 魔女っ子 (!witch)
            elif content.startswith("!witch "):
                if player_data["role"] != "魔女っ子":
                    await message.author.send("あなたは魔女っ子ではありません！")
                    return
                target_name = content[7:].strip()
                if target_name in game["players"] and target_name != my_player_name:
                    game["witch_targets"][my_player_name] = target_name
                    await message.author.send(f"🧙‍♀️ {target_name} の役職は 『{game['players'][target_name]['role']}』 です。")
                else:
                    await message.author.send("⚠️ 有効なプレイヤー名を指定してください。")
                return

    # 3. 投票フェーズ (!vote)
    if game["phase"] == "voting" and game["is_running"]:
        if content.startswith("!vote "):
            my_player_name = None
            for n, p in game["players"].items():
                if not p["is_ai"] and p["user_obj"] and p["user_obj"].id == message.author.id:
                    my_player_name = n
                    break
            
            if my_player_name:
                target_name = content[6:].strip()
                if target_name in game["players"]:
                    game["votes"][my_player_name] = target_name
                    await message.author.send(f"🗳️ **{target_name}** に投票しました。")
                    
                    human_players = [n for n, p in game["players"].items() if not p["is_ai"]]
                    if all(hp in game["votes"] for hp in human_players):
                        await game["channel"].send("📥 全員の投票が完了しました！結果を集計します...")
                        await Tally_and_finish()
                else:
                    await message.author.send("⚠️ 有効なプレイヤー名を指定してください。")
            return

    # 4. 議論フェーズ中の発言
    if game["phase"] == "discussion" and game["is_running"] and not is_dm:
        if content.startswith("!jinro "):
            actual_text = content[7:].strip()
            if actual_text:
                await handle_jinro_command(message, actual_text, author_name)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    
    # ※スマホ環境などで環境変数の設定が難しい場合は、
    # 下記のコメントアウトを外してここに直接トークン文字列を入れて実行してください
    # TOKEN = "ここにDiscordのBotトークンを貼り付ける"

    if TOKEN:
        client.run(TOKEN)
    else:
        print("❌ 错误: DISCORD_BOT_TOKEN が設定されていません。Botのトークンを指定してください。")
