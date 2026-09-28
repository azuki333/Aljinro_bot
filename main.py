if content.startswith('!jinro'):
            parts = content[6:].strip().split(maxsplit=1)
            sub = parts[0].lower() if len(parts) > 0 else ""
            arg_text = parts[1] if len(parts) > 1 else ""

            if sub in ['clear', 'リセット']:
                if game["discussion_task"]:
                    game["discussion_task"].cancel()
                game = {
                    "is_running": False, "mode": None, "phase": "idle", "channel": None, "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {}, "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
                    "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0}
                }
                await message.reply('🔄 リセットしました！')
                return

            if sub in ['watch', '観戦']:
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                await setup_game(message.channel, "watch")
                return

            # 🔴 ここを修正：観戦モードの「next」または「次」を確実にキャッチして議論を進める
            if sub in ['next', '次']:
                if game["is_running"] and game["mode"] == "watch":
                    await generate_ai_discussion(is_watch=True)
                else:
                    await message.reply("⚠️ 現在、観戦モードの進行中ではありません。")
                return

            if sub == "solo":
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                view = RoleCountSelectView("solo", [message.author])
                await message.channel.send(embed=view.create_embed(), view=view)
                return

            if sub in ["start", "multi"]:
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                humans = [message.author] + message.mentions
                mode = "solo" if len(humans) == 1 else "multi"
                view = RoleCountSelectView(mode, humans)
                await message.channel.send(embed=view.create_embed(), view=view)
                return

            # 通常モードの人間からの発言
            if game["is_running"] and game["phase"] == "discussion" and game["mode"] != "watch":
                actual_text = content[6:].strip() or "（進行）"
                await generate_ai_discussion(user_input=f"{message.author.display_name}: {actual_text}")
