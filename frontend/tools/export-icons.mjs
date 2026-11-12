import { build } from 'esbuild'
import { writeFileSync } from 'node:fs'
const r = await build({ entryPoints:['src/icons/index.ts'], bundle:true, write:false, format:'cjs', platform:'node' })
const mod = { exports:{} }
new Function('module','exports', r.outputFiles[0].text)(mod, mod.exports)
const { icons } = mod.exports
const META = {
 'brand-chat':['品牌·多人对话','品牌','两个交叠气泡，前气泡带对话点'],
 chat:['消息','导航','气泡内三点，表示进行中的对话'],
 bubble:['会话','导航','纯气泡轮廓，用于空态'],
 'plus-chat':['新建会话','导航','气泡加号'],
 'door-in':['进入房间','导航','透视门板 + 向内箭头'],
 back:['返回','导航','左向箭头'],
 'chevron-right':['进入','导航','右向折角'],
 send:['发送','导航','向上箭头'],
 stop:['停止生成','导航','实心方块'],
 close:['关闭','导航','交叉'],
 plus:['新增','导航','加号'],
 search:['搜索','导航','放大镜'],
 sort:['排序','导航','递减横线 + 下行箭头'],
 user:['用户','身份','头肩剪影'],
 people:['成员数','身份','两人'],
 group:['房间成员','身份','三人，中间放大两侧外移'],
 robot:['AI 助手','身份','天线机器人头'],
 bolt:['模型','身份','闪电'],
 brain:['Anthropic','身份','双脑叶带中缝'],
 sparkles:['Gemini','身份','四角星芒'],
 sliders:['接口配置','管理','三条滑轨带旋钮'],
 grid:['模型注册表','管理','三方块一圆的分类格'],
 key:['邀请码','管理','钥匙'],
 gear:['系统设置','管理','齿轮'],
 'signal-check':['连通测试','管理','信号弧 + 对勾'],
 refresh:['同步','管理','双向循环箭头'],
 pencil:['编辑','管理','铅笔'],
 trash:['删除','管理','垃圾桶'],
 link:['绑定渠道','管理','链条'],
 star:['设为默认','管理','五角星'],
 ban:['作废','状态','禁止符'],
 pin:['置顶','状态','图钉'],
 'pin-off':['取消置顶','状态','图钉 + 斜杠'],
 copy:['复制','管理','两张叠放的纸'],
 check:['成功','状态','圆内对勾'],
 logout:['退出','导航','门 + 向外箭头'],
 lock:['密码','状态','挂锁'],
 contrast:['主题','状态','半明半暗'],
 moon:['夜间','状态','月牙'],
 sun:['白天','状态','太阳'],
 'cloud-off':['无可用渠道','状态','云 + 斜杠'],
 tray:['空列表','状态','收纳托盘'],
 warning:['警示','状态','三角感叹号'],
}
const out = Object.keys(icons).map(n => ({
  name:n, label:(META[n]||[n,'其他',''])[0], cat:(META[n]||[n,'其他',''])[1],
  desc:(META[n]||[n,'其他',''])[2], shapes:icons[n],
}))
writeFileSync('/tmp/icons.json', JSON.stringify(out))
console.log('导出', out.length, '枚；分类', [...new Set(out.map(o=>o.cat))].join('/'))
