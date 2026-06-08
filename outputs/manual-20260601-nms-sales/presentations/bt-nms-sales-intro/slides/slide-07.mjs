import { C, IMG, bg, footer, kicker, panel, screenshot, smallSource, subcopy, text, title } from "./shared.mjs";

export async function slide07(presentation, ctx) {
  const slide = presentation.slides.add();
  bg(ctx, slide);
  kicker(ctx, slide, "安全控制");
  title(ctx, slide, "远程控制纳入授权、验证和审计边界。", 70, 76, 760, 74, { size: 41 });
  subcopy(ctx, slide, "系统支持远程命令入口；控制动作需在账号权限、二次验证、目标确认和审计记录的约束下执行。", 72, 152, 940, 44, { size: 18.5 });

  await screenshot(ctx, slide, IMG.commandPanel, 148, 238, 350, 424, { caption: "远程控制命令窗口：验证通过后选择方向和模式", fit: "contain", pad: 6 });

  const gates = [
    ["1", "账号权限", "普通操作员不应接触高风险入口"],
    ["2", "二次验证", "验证通过前不显示或不能执行命令"],
    ["3", "目标复核", "确认本站/邻站、方向和模式后发送"],
    ["4", "审计记录", "查看页面提示、用户操作和状态变化"],
  ];
  gates.forEach(([n, h, b], i) => {
    const x = 640 + (i % 2) * 260;
    const y = 268 + Math.floor(i / 2) * 132;
    panel(ctx, slide, x, y, 225, 104, { fill: i === 1 ? C.amberSoft : C.white, border: C.line });
    ctx.addShape(slide, { x: x + 18, y: y + 22, w: 30, h: 30, geometry: "ellipse", fill: i === 1 ? C.amber : C.cyan, line: { style: "solid", fill: "#00000000", width: 0 } });
    text(ctx, slide, n, x + 18, y + 27, 30, 18, { size: 13, color: C.white, bold: true, align: "center" });
    text(ctx, slide, h, x + 62, y + 20, 132, 24, { size: 18, color: C.ink, bold: true });
    text(ctx, slide, b, x + 62, y + 50, 135, 34, { size: 13, color: C.muted, leading: 1.12 });
  });

  panel(ctx, slide, 640, 548, 485, 42, { fill: C.tealDark, border: C.tealDark });
  text(ctx, slide, "控制原则：能远程处置，也要通过权限、验证和记录留痕管住控制风险。", 652, 560, 461, 18, {
    size: 12.5,
    color: C.white,
    bold: true,
    align: "center",
  });

  footer(ctx, slide, smallSource(), 7);
  return slide;
}
