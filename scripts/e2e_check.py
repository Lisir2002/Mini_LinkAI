from playwright.sync_api import sync_playwright
import time

errs=[]
def run():
    with sync_playwright() as p:
        b=p.chromium.launch(executable_path="/root/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome",args=["--no-sandbox"])
        ctx=b.new_context(viewport={"width":375,"height":812},device_scale_factor=2)
        pg=ctx.new_page()
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.on("pageerror", lambda e: errs.append("PAGEERROR: "+str(e)))
        B="http://127.0.0.1:5173"
        def ov(tag):
            o=pg.evaluate("()=>({s:document.documentElement.scrollWidth,c:document.documentElement.clientWidth})")
            print(f"  [{tag}] 宽度 {o['s']}/{o['c']}", "✅" if o['s']<=o['c'] else "❌溢出")
        pg.goto(B+"/", wait_until="networkidle"); pg.wait_for_timeout(600)
        print("1. 未登录落地:", pg.evaluate("location.pathname")); ov("login")
        pg.fill("input[placeholder='手机号 / 邮箱']","admin@demo.com")
        pg.fill("input[placeholder='密码']","AdminPass2026")
        pg.click(".submit"); pg.wait_for_timeout(1200)
        print("2. 首次登录强制改密:", pg.evaluate("location.pathname"))
        pw=pg.query_selector_all("input[type=password]")
        pw[0].fill("AdminPass2026"); pw[1].fill("NewAdmin2026x"); pw[2].fill("NewAdmin2026x")
        pg.click(".form .primary"); pg.wait_for_timeout(1500)
        print("3. 改密后落地:", pg.evaluate("location.pathname")); ov("msgs")

        pg.goto(B+"/admin/channels", wait_until="networkidle"); pg.wait_for_timeout(900)
        print("4. 渠道页标题:", pg.inner_text("h1")); ov("channels")
        pg.click("text=添加接口"); pg.wait_for_timeout(500)
        pg.fill("input[placeholder='例如：DeepSeek 主账号']","本地 Mock 上游")
        pg.fill("input[placeholder='https://api.deepseek.com/v1']","http://127.0.0.1:8097/v1")
        pg.fill("input[type=password]","sk-mock-e2e-1234")
        pg.click(".drawer button.primary:has-text('保存')"); pg.wait_for_timeout(1200)
        print("5. 渠道已创建:", pg.locator(".card .name").first.inner_text())
        pg.screenshot(path="docs/screenshots/渠道配置-移动375.png")
        pg.click("button:has-text('测试连通')"); pg.wait_for_timeout(1800)
        print("6. 连通测试:", pg.locator(".result").first.inner_text())
        pg.click("button:has-text('同步模型')"); pg.wait_for_timeout(1500)
        chips=pg.locator(".dchip").all_inner_texts()
        print("7. 同步到上游模型:", chips)

        pg.goto(B+"/admin/models", wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.click("text=新建模型"); pg.wait_for_timeout(400)
        pg.fill("input[placeholder='例如：smart']","smart")
        pg.fill("input[placeholder='例如：主力模型']","主力模型")
        pg.click(".drawer button.primary:has-text('保存')"); pg.wait_for_timeout(1000)
        pg.click("button:has-text('绑定渠道')"); pg.wait_for_timeout(400)
        pg.fill("input[placeholder='例如：deepseek-chat']","mock-chat")
        pg.click(".drawer button.primary:has-text('确认绑定')"); pg.wait_for_timeout(1000)
        print("8. 模型已建并绑定:", pg.locator(".card .name").first.inner_text()); ov("models")

        pg.goto(B+"/msgs", wait_until="networkidle"); pg.wait_for_timeout(800)
        pg.click("button[aria-label='新建会话']"); pg.wait_for_timeout(500)
        pg.fill("input[placeholder='例如：产品方案讨论']","端到端验证会话")
        pg.click(".drawer button.primary:has-text('创建并开始')"); pg.wait_for_timeout(1500)
        conv_path = pg.evaluate("location.pathname")
        print("9. 进入会话:", conv_path)
        pg.fill("input[placeholder='输入消息，Enter 发送…']","你好，验证一下流式链路")
        pg.click("button[aria-label='发送']")
        pg.wait_for_timeout(4000)
        bubbles=pg.locator(".msg.assistant .bubble").all_inner_texts()
        print("10. AI 流式回复:", (bubbles[-1][:48] if bubbles else "❌ 无"))
        print("11. 用量提示:", pg.locator(".usage").inner_text() if pg.query_selector(".usage") else "无")
        ov("chat")
        pg.screenshot(path="docs/screenshots/AI流式对话-移动375.png")

        pg.goto(B+"/rooms", wait_until="networkidle"); pg.wait_for_timeout(800)
        pg.click("button[aria-label='创建房间']"); pg.wait_for_timeout(400)
        pg.fill("input[placeholder='例如：翻译室']","翻译室")
        pg.fill("input[placeholder='一句话说明这个房间做什么']","贴原文即译，术语统一")
        pg.select_option("select.fi", index=1)
        pg.click(".drawer button.primary:has-text('创建房间')"); pg.wait_for_timeout(1500)
        room_path = pg.evaluate("location.pathname")
        print("12. 进入房间:", room_path)
        pg.fill("input[placeholder='发消息，@AI 触发模型…']","@AI 把 hello world 翻成中文")
        pg.click(".send"); pg.wait_for_timeout(4500)
        ai=pg.locator(".msg.ai .bubble").all_inner_texts()
        print("13. 房间 AI 回复:", (ai[-1][:48] if ai else "❌ 无")); ov("room")

        pg.goto(B+"/me", wait_until="networkidle"); pg.wait_for_timeout(900)
        print("14. 我的页用量:", pg.locator(".quota .lab").first.inner_text().replace("\n"," "))
        pg.click("button[aria-label='切换主题']"); pg.wait_for_timeout(400)
        print("15. 主题切换:", pg.evaluate("document.documentElement.getAttribute('data-theme')"))
        ov("me-dark")

        pg.set_viewport_size({"width":1440,"height":900})
        pg.goto(B+"/admin/channels", wait_until="networkidle"); pg.wait_for_timeout(900)
        side=pg.evaluate("()=>getComputedStyle(document.querySelector('.side')).display")
        print("16. 桌面端侧栏:", side, "✅" if side!="none" else "❌")
        ov("admin-1440")
        pg.screenshot(path="docs/screenshots/管理后台-桌面1440.png")
        pg.set_viewport_size({"width":375,"height":812})
        pg.goto(B+"/msgs", wait_until="networkidle"); pg.wait_for_timeout(700)
        pg.screenshot(path="docs/screenshots/消息列表-移动375.png")
        icon = pg.evaluate("""()=>{const svgs=[...document.querySelectorAll('svg.app-icon')];
            const shapes=svgs.reduce((n,s)=>n+s.querySelectorAll('path,circle,rect,line,polyline,polygon').length,0);
            const r=svgs[0]?.getBoundingClientRect();
            return {count:svgs.length, shapes, w:r?Math.round(r.width):0,
                    legacy:document.querySelectorAll('.material-icons').length,
                    fontLink:!!document.querySelector('link[href*=googleapis]')};}""")
        ok = icon['count']>0 and icon['shapes']>0 and icon['legacy']==0 and not icon['fontLink'] and icon['w']>0
        print("17. 自绘 SVG 图标:", icon, "✅ 全部内联 SVG" if ok else "❌ 存在字体图标或空图标")
        # ── EXT 首批新功能 ─────────────────────────────
        pg.goto(B+room_path, wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.locator(".act:has-text('引用')").first.click(); pg.wait_for_timeout(400)
        assert pg.query_selector(".qbar"), "引用条未出现"
        pg.fill("input[placeholder='发消息，@AI 触发模型…']","引用这条说一下")
        pg.click(".send"); pg.wait_for_timeout(1500)
        assert pg.locator(".qblock").count() > 0, "引用块未渲染"
        print("18. 房间引用发送: ✅ 引用条 + 引用块渲染")
        pg.locator(".act:has-text('引用')").first.click(); pg.wait_for_timeout(300)
        pg.fill("input[placeholder='发消息，@AI 触发模型…']","@AI 针对引用内容展开")
        pg.click(".send"); pg.wait_for_timeout(4500)
        print("19. 房间引用触发 AI:", "✅" if pg.locator(".msg.ai .bubble").count() >= 2 else "❌")
        pg.locator("button[aria-label='有帮助']").first.click(); pg.wait_for_timeout(800)
        on = pg.locator("button[aria-label='有帮助'].on").count()
        pg.locator("button[aria-label='有帮助']").first.click(); pg.wait_for_timeout(800)
        off = pg.locator("button[aria-label='有帮助'].on").count()
        print("20. 反馈投票/取消:", "✅" if on == 1 and off == 0 else f"❌ on={on} off={off}")
        pg.locator("button[aria-label='有帮助']").first.click(); pg.wait_for_timeout(800)
        pg.screenshot(path="docs/screenshots/引用与反馈-移动375.png")

        pg.goto(B+conv_path, wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.locator(".msg.assistant .act:has-text('引用')").first.click(); pg.wait_for_timeout(300)
        pg.fill("input[placeholder='输入消息，Enter 发送…']","接着这条追问")
        pg.click("button[aria-label='发送']"); pg.wait_for_timeout(4500)
        print("21. 单聊引用追问:", "✅" if pg.locator(".qblock").count() > 0 else "❌")

        pg.goto(B+"/msgs", wait_until="networkidle"); pg.wait_for_timeout(800)
        pg.fill("input[placeholder='搜索会话与消息内容']","流式链路"); pg.wait_for_timeout(1500)
        n = pg.locator(".srow").count()
        hl = pg.locator(".snip mark").count()
        print(f"22. 全文搜索: 命中 {n} 条 / 高亮 {hl} 处", "✅" if n > 0 and hl > 0 else "❌")
        pg.locator(".srow").first.click(); pg.wait_for_timeout(1200)
        jumped = "?msg=" in pg.evaluate("location.href")
        print("23. 搜索结果跳转:", pg.evaluate("location.pathname + location.search"), "✅" if jumped else "❌")

        pg.goto(B+"/admin/stats", wait_until="networkidle"); pg.wait_for_timeout(1200)
        print("24. 统计页满意度:", pg.locator(".card b").all_inner_texts())
        pg.click("button:has-text('实时')"); pg.wait_for_timeout(7000)
        online = pg.locator(".card b").first.inner_text()
        sparks = pg.locator(".chart polyline").count()
        chans = pg.locator(".crow").count()
        print(f"25. 实时看板: 在线={online} 曲线={sparks} 渠道行={chans}",
              "✅" if online != "—" and sparks >= 1 and chans >= 1 else "❌")
        ov("stats-live")
        pg.screenshot(path="docs/screenshots/数据统计-实时-移动375.png")

        # ── EXT-011/013/025 新功能 ─────────────────────
        pg.goto(B+conv_path, wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.click("button[aria-label='导出与分享']"); pg.wait_for_timeout(500)
        pg.click("button:has-text('创建并复制链接')"); pg.wait_for_timeout(1200)
        share_url = pg.locator(".stoken").first.inner_text()
        print("26. 分享链接已创建:", share_url[:42] + "…")
        anon = b.new_context(viewport={"width":375,"height":812})
        ap = anon.new_page()
        ap.goto(share_url, wait_until="networkidle"); ap.wait_for_timeout(900)
        shared_msgs = ap.locator(".msg").count()
        print("27. 免登录分享页:", f"渲染 {shared_msgs} 条消息", "✅" if shared_msgs >= 2 else "❌")
        anon.close()
        close_btn = pg.query_selector(".drawer button[aria-label='关闭']") or pg.query_selector(".drawer .close")
        if close_btn:
            close_btn.click()
        else:
            pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)

        pg.goto(B+room_path, wait_until="networkidle"); pg.wait_for_timeout(1500)
        online_txt = pg.locator(".nav-sub, .sub").first.inner_text() if pg.query_selector(".nav-sub, .sub") else ""
        login_r = pg.request.post(B+"/api/auth/login",
                                  data={"email":"admin@demo.com","password":"NewAdmin2026x"})
        tok = login_r.json()["data"]["token"]
        rid_num = room_path.split("/")[-1]
        pg.request.post(B+f"/api/rooms/{rid_num}/messages",
                        data={"content":"WS 实时推送验证"},
                        headers={"Authorization": f"Bearer {tok}"})
        pg.wait_for_timeout(2000)
        ws_seen = pg.locator(".msg .bubble:has-text('WS 实时推送验证')").count()
        print("28. WS 实时推送（无轮询等待）:", "✅ 2 秒内到达" if ws_seen else "❌ 未到达")
        print("   在线人数显示:", "✅" if "人在线" in pg.inner_text("body") else "❌")

        pg.goto(B+"/admin/channels", wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.locator("button:has-text('健康')").first.click(); pg.wait_for_timeout(1000)
        htitle = pg.locator(".drawer h2, .drawer .title").first.inner_text()
        pg.fill("input[placeholder*='oapi.dingtalk.com']","http://127.0.0.1:8097/v1/hook")
        pg.click("button:has-text('保存配置')"); pg.wait_for_timeout(900)
        print("29. 健康抽屉:", htitle, "| 告警配置保存:",
              "✅" if pg.locator(".toast:has-text('已保存')").count() or "已保存" in pg.inner_text("body") else "❌")
        ov("health-drawer")
        pg.screenshot(path="docs/screenshots/渠道健康-移动375.png")

        # ── EXT-016/017 模板市场 ─────────────────────
        pg.goto(B+room_path, wait_until="networkidle"); pg.wait_for_timeout(1200)
        pub = pg.locator("button:has-text('发布为模板')")
        print("30. 房主可见发布入口:", "✅" if pub.count() else "❌")
        pub.click(); pg.wait_for_timeout(400)
        pg.locator("button.go:has-text('确认')").last.click()
        pg.wait_for_timeout(1000)
        print("   发布结果:", "✅" if "已发布" in pg.inner_text("body") else "❌")

        pg.goto(B+"/rooms", wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.click("text=模板市场"); pg.wait_for_timeout(1000)
        tpl_name = pg.locator(".card.tpl .name").first.inner_text()
        print("31. 模板市场卡片:", tpl_name)
        pg.locator(".card.tpl button:has-text('一键开房')").first.click()
        pg.wait_for_timeout(1800)
        cloned_path = pg.evaluate("location.pathname")
        cloned_title = pg.inner_text(".nav-title, h1").split("\n")[0] if pg.query_selector(".nav-title, h1") else ""
        print("32. 一键克隆开房:", cloned_path, cloned_title,
              "✅" if cloned_path.startswith("/r/") and cloned_path != room_path else "❌")
        ov("cloned-room")
        pg.screenshot(path="docs/screenshots/模板市场-移动375.png")

        # ── EXT-014/015 A/B 实验 ─────────────────────
        ch2 = pg.request.post(B+"/api/admin/channels",
                              data={"name":"实测渠道B","type":"openai_compatible",
                                    "base_url":"http://127.0.0.1:8097/v1",
                                    "api_key":"sk-e2e-second-5678","weight":50,"priority":10},
                              headers={"Authorization": f"Bearer {tok}"}).json()["data"]
        models_l = pg.request.get(B+"/api/admin/models",
                                  headers={"Authorization": f"Bearer {tok}"}).json()["data"]["items"]
        m_id = models_l[0]["id"]
        pg.request.post(B+f"/api/admin/models/{m_id}/channels",
                        data={"channel_id": ch2["id"], "upstream_model": "mock-fast"},
                        headers={"Authorization": f"Bearer {tok}"})
        pg.goto(B+"/admin/experiments", wait_until="networkidle"); pg.wait_for_timeout(1000)
        pg.click("button:has-text('新建实验')"); pg.wait_for_timeout(600)
        pg.select_option("select.model-sel", index=1)
        pg.wait_for_timeout(500)
        pg.select_option("select.ch-a", index=1)
        pg.select_option("select.ch-b", index=2)
        pg.click(".drawer button.primary:has-text('创建')"); pg.wait_for_timeout(1200)
        exp_created = pg.locator(".exp-card").count()
        print("33. 实验已创建:", "✅" if exp_created >= 1 else "❌")
        pg.goto(B+conv_path, wait_until="networkidle"); pg.wait_for_timeout(800)
        pg.fill("input[placeholder='输入消息，Enter 发送…']","实验路由验证")
        pg.click("button[aria-label='发送']"); pg.wait_for_timeout(4000)
        pg.goto(B+"/admin/experiments", wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.locator("button:has-text('报告')").first.click(); pg.wait_for_timeout(1000)
        rec = pg.locator(".recommend").inner_text() if pg.query_selector(".recommend") else ""
        rows = pg.locator(".bucket-row").count()
        print("34. 分桶报告:", f"{rows} 桶 | 建议: {rec[:36]}…", "✅" if rows == 2 and rec else "❌")
        pg.screenshot(path="docs/screenshots/AB实验报告-移动375.png")
        pg.locator(".drawer button:has-text('结束实验并回退')").click(); pg.wait_for_timeout(900)
        ended = "已结束" in pg.inner_text("body")
        print("35. 结束实验回退权重路由:", "✅" if ended else "❌")
        ov("experiments")

        # ── EXT-020/021 图片上传 ─────────────────────
        import struct as _st, zlib as _zl
        def _make_png(w, h):
            rows = b""
            for y in range(h):
                rows += b"\x00"
                for x in range(w):
                    rows += bytes((int(235 * x / w) + 20, int(150 * y / h) + 40, 210 - int(110 * x / w)))
            def _chunk(t, d):
                c = t + d
                return _st.pack(">I", len(d)) + c + _st.pack(">I", _zl.crc32(c))
            return (b"\x89PNG\r\n\x1a\n"
                    + _chunk(b"IHDR", _st.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                    + _chunk(b"IDAT", _zl.compress(rows)) + _chunk(b"IEND", b""))
        png = _make_png(320, 240)
        models_l = pg.request.get(B+"/api/admin/models",
                                  headers={"Authorization": f"Bearer {tok}"}).json()["data"]["items"]
        m0 = models_l[0]
        pg.request.patch(B+f"/api/admin/models/{m0['id']}",
                         data={"version": m0["version"], "supports_vision": True},
                         headers={"Authorization": f"Bearer {tok}"})
        pg.goto(B+conv_path, wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.set_input_files("input[type=file]",
                           files=[{"name":"测试图.png","mimeType":"image/png","buffer":png}])
        pg.wait_for_timeout(1500)
        preview = pg.locator(".attach-chip").count()
        print("36. 上传预览:", "✅" if preview else "❌")
        pg.fill("input[placeholder='输入消息，Enter 发送…']","看看这张图")
        pg.click("button[aria-label='发送']"); pg.wait_for_timeout(4500)
        imgs = pg.locator(".msg img").count()
        print("37. 气泡内鉴权图片渲染:", "✅" if imgs >= 1 else "❌")
        ov("chat-image")
        pg.screenshot(path="docs/screenshots/图片对话-移动375.png")

        # ── EXT-026 统计预聚合 ─────────────────────
        rc = pg.request.post(B+"/api/admin/stats/recompute",
                             headers={"Authorization": f"Bearer {tok}"})
        print("38. 预聚合触发:", rc.json()["data"])
        pg.goto(B+"/admin/stats", wait_until="networkidle"); pg.wait_for_timeout(1500)
        trend = pg.locator(".trend polyline").count()
        print("39. 用量趋势曲线:", "✅" if trend >= 1 else "❌")
        ov("stats-trend")

        # ── FR 好友与私聊（双用户双上下文） ─────────────
        AH = {"Authorization": f"Bearer {tok}"}
        codes = pg.request.post(B+"/api/admin/invite-codes", data={"count":1,"max_uses":1},
                                headers=AH).json()["data"]["codes"]
        reg = pg.request.post(B+"/api/auth/register",
                              data={"email":"dm@test.com","password":"DmPass2026x",
                                    "nickname":"私聊实测员","invite_code":codes[0]})
        print("40. 第二用户注册:", reg.status)
        ctx2 = b.new_context(viewport={"width":375,"height":812})
        p2 = ctx2.new_page()
        p2.on("console", lambda m: errs.append("P2:"+m.text) if m.type=="error" else None)
        p2.goto(B+"/login", wait_until="networkidle"); p2.wait_for_timeout(500)
        p2.fill("input[placeholder='手机号 / 邮箱']","dm@test.com")
        p2.fill("input[placeholder='密码']","DmPass2026x")
        p2.click(".submit"); p2.wait_for_timeout(1500)

        pg.goto(B+"/friends", wait_until="networkidle"); pg.wait_for_timeout(900)
        pg.click("button[aria-label='添加好友']"); pg.wait_for_timeout(400)
        pg.fill("input[placeholder='搜索昵称或邮箱']","私聊实测员"); pg.wait_for_timeout(1200)
        pg.locator(".user-row button:has-text('申请')").first.click(); pg.wait_for_timeout(1000)
        print("41. 好友申请已发送:", "✅" if "已" in pg.inner_text("body") else "❌")

        p2.goto(B+"/friends", wait_until="networkidle"); p2.wait_for_timeout(900)
        p2.click("button.chip:has-text('新的朋友')"); p2.wait_for_timeout(600)
        p2.locator(".req-row button:has-text('同意')").first.click(); p2.wait_for_timeout(1000)
        print("42. 对方同意申请:", "✅" if p2.locator(".friend-row").count() or "好友" in p2.inner_text("body") else "❌")

        pg.goto(B+"/friends", wait_until="networkidle"); pg.wait_for_timeout(1000)
        pg.locator(".friend-row").first.click(); pg.wait_for_timeout(1200)
        dm_path = pg.evaluate("location.pathname")
        pg.fill("input[placeholder='发消息…']","好友私聊实测"); pg.click("button[aria-label='发送']")
        pg.wait_for_timeout(1200)
        p2.goto(B+"/friends", wait_until="networkidle"); p2.wait_for_timeout(900)
        p2.locator(".friend-row").first.click(); p2.wait_for_timeout(1500)
        got = p2.locator(".dm-msg:has-text('好友私聊实测')").count()
        print("43. 私聊消息到达对方:", "✅" if got else "❌", dm_path)
        p2.fill("input[placeholder='发消息…']","收到回复"); p2.click("button[aria-label='发送']")
        pg.wait_for_timeout(2500)
        reply = pg.locator(".dm-msg:has-text('收到回复')").count()
        print("44. 回复实时到达（WS）:", "✅" if reply else "❌")
        read_state = pg.locator(".read-state:has-text('已读')").count()
        print("45. 已读回执:", "✅" if read_state else "❌")
        ov("dm-chat")
        pg.screenshot(path="docs/screenshots/好友私聊-移动375.png")

        # ── 审查修复：私聊图片（此前 E2E 盲区） ─────────
        pg.set_input_files("input[type=file]",
                           files=[{"name":"私聊图.png","mimeType":"image/png","buffer":png}])
        pg.wait_for_timeout(1500)
        pg.fill("input[placeholder='发消息…']","发你一张图"); pg.click("button[aria-label='发送']")
        pg.wait_for_timeout(1500)
        p2.goto(B+"/friends", wait_until="networkidle"); p2.wait_for_timeout(800)
        p2.locator(".friend-row").first.click(); p2.wait_for_timeout(2000)
        dm_imgs = p2.locator(".dm-msg img").count()
        print("46. 私聊图片收件人可见:", "✅" if dm_imgs >= 1 else "❌")
        pg.wait_for_timeout(500)
        pg.screenshot(path="docs/screenshots/私聊图片-移动375.png")
        ctx2.close()

        print("\n控制台错误:", errs[:6] if errs else "无 ✅")
        b.close()
run()
