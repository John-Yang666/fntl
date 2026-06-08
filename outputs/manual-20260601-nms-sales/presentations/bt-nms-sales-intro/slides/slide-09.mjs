import { C, bg, footer, iconLabel, kicker, line, panel, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide09(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "部署架构");
  title(ctx, slide, "服务端与边缘 Agent 解耦，适配现场网络和设备协议。", 70, 76, 810, 74, { size: 40 });
  subcopy(ctx, slide, "生产环境通过 Docker Compose 编排前端、BT/SY 后端、PostgreSQL、Redis、Celery、Nginx 等组件；Windows 侧 Agent 负责现场 UDP 或串口链路。", 72, 154, 920, 54, { size: 18 });

  panel(ctx, slide, 80, 258, 490, 300, { fill: "#FFFFFF", border: "#C8D1D8" });
  text(ctx, slide, "中心服务端", 110, 286, 180, 30, { size: 24, color: C.tealDark, bold: true });
  const services = [
    ["Vue 前端", "38173", "Monitor"],
    ["BT 后端 / API", "8000", "Server"],
    ["SY 后端 / API", "8001", "ServerCog"],
    ["PostgreSQL", "持久数据", "Database"],
    ["Redis / Streams", "缓存与消息", "Route"],
    ["Celery / Nginx", "任务与代理", "Workflow"],
  ];
  for (let i = 0; i < services.length; i += 1) {
    const [h, b, icon] = services[i];
    const x = 110 + (i % 2) * 220;
    const y = 338 + Math.floor(i / 2) * 62;
    panel(ctx, slide, x, y, 190, 46, { fill: i === 4 ? C.cyanSoft : C.paper2, border: C.line });
    await iconLabel(ctx, slide, icon, h, x + 12, y + 12, { iconSize: 18, w: 120, size: 14, color: i === 4 ? C.cyan : C.tealDark });
    text(ctx, slide, b, x + 120, y + 14, 56, 16, { size: 10.5, color: C.muted, align: "right" });
  }

  panel(ctx, slide, 706, 258, 420, 300, { fill: "#FFFFFF", border: "#C8D1D8" });
  text(ctx, slide, "现场边缘侧", 736, 286, 180, 30, { size: 24, color: C.tealDark, bold: true });
  const agents = [
    ["bt_agent", "BT UDP 数据采集与命令发送", "Radio"],
    ["bt_agent_serial", "BT 串口 TestData 帧读取", "Cable"],
    ["sy_agent", "SY 串口收发与运行状态输出", "Terminal"],
  ];
  for (let i = 0; i < agents.length; i += 1) {
    const [h, b, icon] = agents[i];
    const y = 346 + i * 70;
    panel(ctx, slide, 736, y, 330, 54, { fill: i === 2 ? C.amberSoft : C.paper2, border: C.line });
    await iconLabel(ctx, slide, icon, h, 756, y + 11, { iconSize: 19, w: 180, size: 14.5, color: i === 2 ? C.amber : C.cyan });
    text(ctx, slide, b, 788, y + 33, 236, 16, { size: 10.8, color: C.muted });
  }

  ctx.addShape(slide, { x: 574, y: 394, w: 126, h: 4, fill: C.cyan, line: line(C.cyan, 0) });
  text(ctx, slide, "Redis Streams\n解耦采集与控制", 588, 414, 104, 34, { size: 13, color: C.tealDark, bold: true, align: "center", leading: 1.1 });
  ctx.addShape(slide, { x: 570, y: 392, w: 12, h: 12, geometry: "ellipse", fill: C.cyan, line: line(C.cyan, 0) });
  ctx.addShape(slide, { x: 695, y: 392, w: 12, h: 12, geometry: "ellipse", fill: C.cyan, line: line(C.cyan, 0) });

  text(ctx, slide, "部署价值：现场网络复杂时，Agent 负责贴近设备，服务端负责权限、数据和页面，部署边界更清楚。", 82, 612, 880, 30, {
    size: 16,
    color: C.ink,
    bold: true,
  });

  footer(ctx, slide, smallSource(), 9);
  return slide;
}
