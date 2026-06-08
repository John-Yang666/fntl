import { C, bg, chip, divider, footer, iconLabel, kicker, line, panel, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide03(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "系统定位");
  title(ctx, slide, "系统把 BT/SY 两类设备纳入统一控制台。", 70, 78, 710, 66, { size: 42 });
  subcopy(ctx, slide, "前端不直接接触现场设备；实时采集和下行控制通过 Redis Streams 与边缘 Agent 解耦，既适配现场链路，也保留后端权限和审计边界。", 72, 150, 900, 52, { size: 19 });

  const laneY = 256;
  const cols = [
    ["前端控制台", "Vue 控制台\n拓扑 / 告警 / 记录 / 控制", "Monitor", C.tealDark],
    ["BT 后端", "Django / DRF / Channels\n设备台账、告警、记录", "Server", C.cyan],
    ["SY 后端", "三方向状态、原始帧\n变化量事件、串口命令", "Layers", C.amber],
    ["Redis Streams", "stream:udp:packets\nsy.raw / sy-serial-commands", "Route", C.green],
    ["边缘 Agent", "Windows 受保护 Agent\nUDP / 串口收发", "Radio", C.red],
    ["现场设备", "线路、车间、方向邻站\n状态字 / 继电器 / 告警", "Network", C.ink],
  ];
  const cardW = 176;
  for (let i = 0; i < cols.length; i += 1) {
    const [h, b, icon, color] = cols[i];
    const x = 70 + i * 190;
    panel(ctx, slide, x, laneY, cardW, 148, { fill: C.white, border: i === 0 ? C.tealDark : C.line, borderWidth: i === 0 ? 1.6 : 1 });
    ctx.addShape(slide, { x, y: laneY, w: cardW, h: 7, fill: color, line: line(color, 0) });
    text(ctx, slide, h, x + 16, laneY + 24, cardW - 32, 24, { size: 20, bold: true, color: C.ink });
    text(ctx, slide, b, x + 16, laneY + 60, cardW - 32, 54, { size: 13.5, color: C.muted, leading: 1.13 });
    await iconLabel(ctx, slide, icon, "", x + cardW - 46, laneY + 106, { iconSize: 24, w: 0, color });
    if (i < cols.length - 1) {
      ctx.addShape(slide, { x: x + cardW + 10, y: laneY + 72, w: 22, h: 3, fill: C.line, line: line(C.line, 0) });
      ctx.addShape(slide, { x: x + cardW + 28, y: laneY + 67, w: 7, h: 13, fill: C.line, line: line(C.line, 0) });
    }
  }

  divider(ctx, slide, 70, 470, 1080, C.line);
  const points = [
    ["统一入口", "BT/SY 登录后在同一套前端选择系统类型，减少值守切换成本。"],
    ["链路隔离", "Web 服务不直接控制现场串口或 UDP 通道，通过 Stream 与 Agent 交换。"],
    ["审计留痕", "远程命令、继电器动作、用户操作等进入记录，便于复盘。"],
  ];
  points.forEach(([h, b], i) => {
    const x = 80 + i * 365;
    chip(ctx, slide, h, x, 508, 116, { fill: i === 1 ? C.amberSoft : C.cyanSoft, border: i === 1 ? "#F6CD8B" : "#BCECF1" });
    text(ctx, slide, b, x, 552, 310, 44, { size: 15, color: C.muted, leading: 1.16 });
  });

  footer(ctx, slide, smallSource(), 3);
  return slide;
}
