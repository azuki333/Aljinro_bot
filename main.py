import discord, asyncio, os
import game_logic as logicpy

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("------")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content.strip()

    # DMでの投票や夜の行動処理
    if isinstance(message.channel, discord.DMChannel):
        if not logicpy.game["is_running"]:
            await message.channel.send("現在進行中のゲームはありません。")
            return

        # プレイヤー自身の特定
        my_name = None
        for n, p in logicpy.game["players"].items():
            if p.get("user_obj") and p["user_obj"].id == message.author.id:
                my_name = n
                break

        if not my_name:
            await message.channel.send("あなたは現在のゲームに参加していません。")
            return

        # 投票フェーズの処理
        if logicpy.game["phase"] == "voting" and content.startswith("!vote"):
            target = content[5:].strip()
            if target in logicpy.game["players"] or target == "墓場":
                logicpy.game["votes"][my_name] = target
                await message.channel.send(f"🗳️ **{target}** に投票しました。")
                
                # 全員（人間＋AI）の投票が揃ったら集計
                if len(logicpy.game["votes"]) == len(logicpy.game["players"]):
                    await logicpy.Tally_and_finish()
            else:
                await message.channel.send("⚠️ 存在するプレイヤー名または「墓場」を指定してください。")
            return

        # 夜の行動（占い・怪盗など）
        if logicpy.game["phase"] == "night":
            p_data = logicpy.game["players"][my_name]
            if content.startswith("!fortune "):
                if p_data["role"] != "占い師":
                    await message.channel.send("あなたす占い師ではありません。")
                    return
                target = content[9:].strip()
                if target == "墓場":
                    await message.channel.send(f"🔮 墓場のカード: 『{logicpy.game['center_cards'][0]}』, 『{logicpy.game['center_cards'][1]}』")
                elif target in logicpy.game["players"] and target != my_name:
                    await message.channel.send(f"🔮 {target} の役職は 『{logicpy.game['players'][target]['role']}』 です。")
                else:
                    await message.channel.send("⚠️ 正しい対象を指定してください。")
            elif content.startswith("!steal "):
                if p_data["role"] != "怪盗":
                    await message.channel.send("あなたは怪盗ではありません。")
                    return
                target = content[7:].strip()
                if target in logicpy.game["players"] and target != my_name:
                    my_old = p_data["role"]
                    target_role = logicpy.game["players"][target]["role"]
                    logicpy.game["players"][my_name]["role"] = target_role
                    logicpy.game["players"][target]["role"] = my_old
                    await message.channel.send(f"🕵️ {target} から役職を盗みました！ あなたの新しい役職は 『{target_role}』 です。")
                else:
                    await message.channel.send("⚠️ 正しいプレイヤーを指定してください。")
            return

        return

    # サーバーチャンネルでのコマンド処理
    if content.startswith("!jinro"):
        parts = content.split()
        if len(parts) > 1 and parts[1] == "reset":
            logicpy.reset_game_state()
            await message.channel.send("🔄 ゲームを強制リセットしました。")
            return

        if len(parts) > 1 and parts[1] == "solo":
            if logicpy.game["is_running"]:
                await message.channel.send("⚠️ 既にゲームが進行中です。")
                return
            logicpy.reset_game_state()
            await message.channel.send("🎴 **ソロモードの役職枚数設定**", view=logicpy.RoleCountSelectView("solo", [message.author]))
            return

        if len(parts) > 1 and parts[1] == "multi":
            if logicpy.game["is_running"]:
                await message.channel.send("⚠️ 既にゲームが進行中です。")
                return
            logicpy.reset_game_state()
            await message.channel.send("👥 参加者を募集中...（参加したい人は `!join` と送信してください。ホストが `!start` で開始します）")
            # 簡単な参加受付用のテンポラリ変数
            logicpy.game["pending_multi_host"] = message.author
            logicpy.game["pending_multi_users"] = [message.author]
            logicpy.game["phase"] = "recruiting"
            logicpy.game["channel"] = message.channel
            return

        if len(parts) > 1 and parts[1] == "watch":
            if logicpy.game["is_running"]:
                await message.channel.send("⚠️ 既にゲームが進行中です。")
                return
            logicpy.reset_game_state()
            asyncio.create_task(logicpy.setup_game(message.channel, "watch"))
            return

        if len(parts) > 1 and parts[1] == "next" and logicpy.game["mode"] == "watch":
            await logicpy.generate_ai_discussion("（次のターンへ進む）", is_watch=True)
            return

        # 議論中の発言 or AIへの話しかけ
        if logicpy.game["is_running"] and logicpy.game["phase"] == "discussion":
            actual_text = content[6:].strip()
            await logicpy.handle_jinro_command(message, actual_text, message.author.display_name)
            return

        await message.channel.send("🐺 **ワンナイト人狼ボットの使い方**\n- `!jinro solo` : ソロモード開始\n- `!jinro multi` : マルチモード募集\n- `!jinro watch` : 観戦モード開始\n- `!jinro reset` : リセット")

    # マルチモードの参加受付
    if content == "!join" and logicpy.game.get("phase") == "recruiting":
        user = message.author
        if user not in logicpy.game["pending_multi_users"]:
            logicpy.game["pending_multi_users"].append(user)
            await message.channel.send(f"👤 {user.display_name} が参加しました！（現在 {len(logicpy.game['pending_multi_users'])}人）")
        return

    # マルチモードのゲーム開始
    if content == "!start" and logicpy.game.get("phase") == "recruiting":
        if message.author == logicpy.game.get("pending_multi_host"):
            users = logicpy.game["pending_multi_users"]
            if len(users) > 5:
                await message.channel.send("⚠️ 人間は最大5人まで参加可能です。")
                return
            await message.channel.send(f"🎴 参加者 {len(users)}名で役職設定に進みます！", view=logicpy.RoleCountSelectView("multi", users))
        return

if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN is missing.")
    else:
      client.run(TOKEN)
