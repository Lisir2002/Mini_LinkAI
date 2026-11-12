import { build } from 'esbuild'
import { writeFileSync } from 'node:fs'
const r = await build({ entryPoints:['src/icons/index.ts'], bundle:true, write:false, format:'cjs', platform:'node' })
const mod = { exports:{} }
new Function('module','exports', r.outputFiles[0].text)(mod, mod.exports)
const { icons } = mod.exports
const LABEL = {
 'brand-chat':'品牌·多人对话', chat:'消息', bubble:'会话', 'plus-chat':'新建会话', 'door-in':'进入房间',
 back:'返回', 'chevron-right':'进入', send:'发送', stop:'停止生成', close:'关闭', plus:'新增',
 search:'搜索', sort:'排序', user:'用户', people:'成员数', group:'房间成员', robot:'AI 助手',
 bolt:'模型', brain:'Anthropic', sparkles:'Gemini', sliders:'接口配置', grid:'模型注册表',
 key:'邀请码', gear:'系统设置', 'signal-check':'连通测试', refresh:'同步', pencil:'编辑',
 trash:'删除', link:'绑定渠道', star:'设为默认', ban:'作废', pin:'置顶', 'pin-off':'取消置顶',
 copy:'复制', check:'成功', logout:'退出', lock:'密码', contrast:'主题', moon:'夜间', sun:'白天',
 'cloud-off':'无可用渠道', tray:'空列表', warning:'警示',
}
const cells = Object.keys(icons).map(n => {
  const shapes = icons[n].map(s => '<'+s.tag+' '+Object.entries(s.attrs).map(([k,v])=>`${k}="${v}"`).join(' ')+'/>').join('')
  return `<figure><div class="box"><svg viewBox="0 0 24 24" width="56" height="56" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${shapes}</svg></div>
  <figcaption><b>${LABEL[n]??n}</b><code>${n}</code></figcaption></figure>`
}).join('')
writeFileSync('../docs/screenshots/icons-gallery.html', `<!DOCTYPE html><html lang="zh"><meta charset="utf-8"><title>自绘图标总览</title>
<style>body{margin:0;background:#F6F7F8;color:#101114;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
header{padding:22px 26px 6px}h1{font-size:20px;margin:0}p{font-size:13px;color:#7A8089;margin:6px 0 0}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;padding:18px 26px 30px}
figure{margin:0;background:#fff;border:1px solid #E7E9EC;border-radius:10px;padding:12px 8px;text-align:center}
.box{height:64px;display:flex;align-items:center;justify-content:center;color:#101114}
figcaption b{display:block;font-size:12px;margin-top:6px}figcaption code{font-size:10px;color:#A2A8B0}
figure:nth-child(7n+3) .box{color:#2E5BFF}figure:nth-child(7n+5) .box{color:#14A44D}figure:nth-child(7n+6) .box{color:#D92D20}
</style><header><h1>自绘 SVG 图标总览 · ${Object.keys(icons).length} 枚</h1>
<p>统一 24×24 网格 / 1.7 描边 / 圆头圆角 / currentColor 继承语义色</p></header><div class="grid">${cells}</div></html>`)
console.log('gallery ok', Object.keys(icons).length)
